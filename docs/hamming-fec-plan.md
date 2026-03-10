# Hamming(12,8) Forward Error Correction Plan

## Context

TemporalCloak encodes messages as bit sequences transmitted via timing delays between HTTP chunks. Over the internet, timing jitter can flip individual bits — the benchmark shows character-level errors like `'s'→'{'` (1 bit flip) and `'a'→'c'` (1 bit flip). These are classic single-bit errors within a character byte.

Adding Hamming(12,8) FEC would allow the decoder to **detect and correct any single-bit error per character**, eliminating the most common failure mode without drastically increasing overhead.

## How Hamming(12,8) Works

Given 8 data bits (d1–d8), compute 4 parity bits (p1, p2, p4, p8). The 12-bit codeword is interleaved by position:

```
Position:  1   2   3   4   5   6   7   8   9  10  11  12
Bit:      p1  p2  d1  p4  d2  d3  d4  p8  d5  d6  d7  d8
```

Each parity bit covers positions where its bit index is set:
- p1 (pos 1): covers positions 1,3,5,7,9,11
- p2 (pos 2): covers positions 2,3,6,7,10,11
- p4 (pos 4): covers positions 4,5,6,7,12
- p8 (pos 8): covers positions 8,9,10,11,12

**Encoding:** Compute each parity bit as XOR of the data bits it covers.

**Decoding:** Recompute all 4 parity bits from the received 12 bits. The 4-bit result (syndrome) is:
- `0000` → no error
- Non-zero → syndrome value = position of the flipped bit; flip it to correct

## Overhead

| Metric | Current | With Hamming |
|--------|---------|-------------|
| Bits per character | 8 | 12 |
| 50-char message bits | 400 | 600 |
| Total wire bits (incl. boundaries, checksum) | ~440 | ~640 |
| Overhead | — | +50% |
| Extra time per message (avg, at 0.15s/bit) | — | ~30s |

## Architecture

### Layer Placement

```
              Current                          With FEC
              ───────                          ────────
String:       "Hello"                          "Hello"
                │                                │
Message bits: 0100100001100101...               0100100001100101...
                │                                │
                │                          ┌─────┴─────┐
                │                          │ Hamming    │
                │                          │ Encode     │
                │                          │ 8→12 bits  │
                │                          └─────┬─────┘
                │                                │
                │                          FEC bits: 011100100101...
                │                                │
Wire format:  [BOUNDARY][MSG][CHKSUM][BOUNDARY]  [BOUNDARY][FEC_MSG][CHKSUM][BOUNDARY]
```

FEC sits **inside** the wire format — boundaries and checksum wrap the FEC-encoded bits. This means:
- Boundary markers are NOT Hamming-encoded (they're fixed calibration patterns)
- The XOR checksum covers the FEC-encoded bits (not raw message)
- The decoder applies Hamming correction first, then reassembles characters

### Files to Modify

1. **`temporal_cloak/encoding.py`** — Add Hamming encode step in `encode_message()`
2. **`temporal_cloak/decoding.py`** — Add Hamming decode step in `decode()`
3. **New: `temporal_cloak/hamming.py`** — Pure Hamming(12,8) encode/decode functions
4. **`tests/`** — New test file for Hamming functions + integration tests

### New Module: `temporal_cloak/hamming.py`

```
hamming_encode_byte(byte: int) -> BitArray      # 8 bits → 12 bits
hamming_decode_block(block: Bits) -> tuple[int, int]  # 12 bits → (byte, corrections)
hamming_encode_message(data: BitArray) -> BitArray    # N*8 bits → N*12 bits
hamming_decode_message(data: BitArray) -> tuple[BitArray, int]  # N*12 bits → (N*8 bits, total_corrections)
```

### Encoder Changes (`encoding.py`)

In `encode_message()`, after converting the string to bits:

```python
# Current:
self._message_bits = BitArray(bytes=message.encode('ascii'))

# New:
raw_bits = BitArray(bytes=message.encode('ascii'))
self._message_bits = hamming_encode_message(raw_bits)
```

### Decoder Changes (`decoding.py`)

In `decode()`, before converting bits to string:

```python
# Current:
message_bytes = message.tobytes()
decoded_message = message_bytes.decode('ascii')

# New:
corrected_bits, num_corrections = hamming_decode_message(message)
message_bytes = corrected_bits.tobytes()
decoded_message = message_bytes.decode('ascii')
```

## Wire Format Compatibility

This is a **breaking change** to the wire format. Old encoders and new decoders (or vice versa) will not interoperate. Options:

1. **Clean break** — just change it, no backward compatibility needed (recommended for now since this is a demo/research project)
2. **Version bit** — use an unused bit in the boundary marker to signal FEC vs non-FEC (future option)

## Verification

1. **Unit tests for Hamming module:**
   - Encode/decode round-trip with no errors
   - Single-bit error correction for every possible error position (12 positions × multiple byte values)
   - Two-bit error detection (syndrome is non-zero but correction is wrong — verify detection)

2. **Integration tests:**
   - `encode_message()` → `decode()` round-trip with FEC
   - Inject single-bit flip into encoded stream, verify correction
   - Run existing test suite — should pass after updating expected bit counts

3. **Benchmark:**
   - Run `scripts/benchmark.py` against live server
   - Compare exact_match rate and BER with/without FEC
   - Expect higher exact_match rate, especially for messages that previously had 1-bit errors

## Risks

- **Two-bit errors** within a single 12-bit block will be **miscorrected** (Hamming corrects to the wrong value silently). The existing checksum will catch this.
- **Longer messages** = more chunks = more total time. A 50-char message goes from ~70s to ~100s with the current image size and timing values.
- **Bit alignment**: message length must be a multiple of 8 bits for Hamming to work cleanly. Current ASCII-only constraint guarantees this.
