# Delay Compensation: Fixing Shifted Timing Gaps

## Problem

When decoding timing-based steganography, the client measures the delay between consecutive chunk arrivals. However, network buffering and TCP behavior can cause delays to "leak" from one gap to the next.

### How it works

The server sends chunks with intentional delays: 0ms for a 1-bit, 300ms for a 0-bit. The client measures gap-to-gap timing and classifies each gap as 1 or 0 based on a threshold (~131ms).

The problem: delays are not discrete events — they're continuous. When one gap runs long, it steals time from the next gap.

### Example from real data (indices 19-21)

Server intended delays: `[0ms, 300ms, 0ms, 300ms]` → bits `[1, 0, 1, 0]`

What happened:
```
Index 18: Expected 1 (0ms)   → Observed 0.4ms   ✓  Normal
Index 19: Expected 0 (300ms) → Observed 0.2ms   ✗  Server slept 300ms but the chunk was
                                                     already in the TCP send buffer — client
                                                     received it immediately
Index 20: Expected 1 (0ms)   → Observed 466ms   ✗  Absorbed index 19's missing 300ms delay
                                                     plus its own transit time
Index 21: Expected 0 (300ms) → Observed 0.5ms   ✗  Server had already sent this while the
                                                     client was stuck waiting for index 20
```

Three consecutive bit flips from a single delayed chunk. The total time is conserved (~466ms across indices 19-21 vs expected ~300ms), but the delay landed on the wrong gap.

### Same pattern at other mismatches

- **Index 47**: Expected 0 (300ms), observed 61ms. Next gap (index 48) got 352ms.
- **Index 176**: Expected 0 (300ms), observed 109ms. Next gap (index 177) got 290ms.

In every case, an oversized delay on one gap is followed by an undersized delay on the next.

## Proposed Solution: Carry-Forward Compensation

Since we already fetch the server config (`bit_0_delay`), the decoder knows the maximum intentional delay. When a gap exceeds that maximum, the excess is jitter that was stolen from the next gap.

### Algorithm

```python
max_expected = server_config.bit_0_delay * 1.1   # 330ms with 10% margin
carry = 0.0

for each raw_delay in gaps:
    corrected = raw_delay + carry
    if corrected > max_expected:
        carry = corrected - max_expected
        corrected = max_expected
    else:
        carry = 0.0
    classify_bit(corrected)
```

### Walkthrough with real data (indices 19-21)

```
max_expected = 0.330s, carry starts at 0.0

Index 18: raw=0.0004 + carry=0.000 = 0.0004  → bit 1 ✓  carry=0
Index 19: raw=0.0002 + carry=0.000 = 0.0002  → bit 1 ✗  carry=0
                                                (still wrong — the delay hasn't arrived yet)
Index 20: raw=0.4664 + carry=0.000 = 0.4664  → exceeds 0.330!
          corrected=0.330 → bit 0              carry=0.136
Index 21: raw=0.0005 + carry=0.136 = 0.1365  → bit 0     carry=0
```

Result: bits decode as `[1, 1, 0, 0]` — indices 20 and 21 are now correct, but index 19 is still wrong (was `[1, 0, 1, 0]` expected).

### Limitation

Carry-forward fixes the *receiving* side of the shift (the gap that absorbed extra delay) and redistributes it to the next gap. But it cannot fix the *originating* gap (index 19) because at that point the carry is still zero — we don't know the delay was stolen until we see the oversized gap that follows.

This reduces the error from 3 flipped bits to 1 flipped bit per incident. For the full dataset:
- Indices 19-21: 3 errors → 1 error (index 19)
- Index 47: 1 error → 0 errors (47 gets carry from prior, or 48 absorbs and redistributes)
- Index 176: 1 error → 0 errors (same pattern)

### Where to implement

Two options:

1. **In `AutoDecoder.mark_time()`** — apply compensation as bits arrive. Requires passing `server_config` to the decoder. Corrects bits in real-time during streaming.

2. **As a post-processing pass** — after all chunks are received, reprocess `time_delays` with compensation and re-classify. Simpler, doesn't change the streaming decoder, but only improves the final result.

Option 2 is safer to start with since it doesn't change the live decoding path.

### Open questions

- Should the carry ever decay? If a gap is oversized due to a genuine network stall (not delay shifting), carrying all excess forward could corrupt the next gap.
- Should compensation be bidirectional? We could do a second pass in reverse to catch the originating gap. But this risks over-correcting.
- What margin factor for `max_expected`? 10% (1.1x) seems reasonable given the observed data, but this could be tuned.
