# Improving TemporalCloak Encode/Decode Accuracy

## Context

TemporalCloak hides messages in timing delays between data transmissions. The current implementation has several accuracy issues: the first decoded bit is always garbage (connection overhead mistaken for an encoded delay), messages lack an end boundary so single messages never decode as "complete", there's no error detection for bit misclassification from timing jitter, and the delay gap is narrow enough that OS scheduling can cause errors.

---

## Accuracy Problems Found

### 1. No End Boundary Marker

The encoder only prepends `0xFF00` to the message. The decoder needs a *second* `0xFF00` to know the message is complete. In Demo 1's infinite loop, the next iteration's start boundary accidentally serves as the previous message's end boundary. But for a single message (or Demo 2's one-shot quote), the decoder never sets `completed=True`.

**File:** `TemporalCloakEncoding.py` line 46 — only calls `prepend()`, never `append()`

### 2. First Bit Is Always Garbage

Both demos measure the time from `start_timer()` to the first data arrival. This includes connection establishment overhead (TCP handshake, HTTP request/response), not an encoded delay. This injects a wrong bit at the start of every decode, corrupting boundary detection.

**Demo 1** (`demo1_server.py` lines 39-42): The comment says "throw away the first time diff" but `mark_time()` is still called, recording it as a real bit.

**Demo 2** (`temporal_cloak_cli_decoder.py` lines 14-21): The first `mark_time()` measures HTTP overhead + first encoded delay, conflating them.

### 3. Narrow Timing Margin

| Parameter | Value |
|-----------|-------|
| Bit 1 delay | 0.00s |
| Bit 0 delay | 0.05s |
| Threshold | 0.03s |
| Margin for bit 1 | 0–30ms |
| Margin for bit 0 | 30–50ms |

`time.sleep(0.0)` yields the thread but the OS scheduler can introduce 5–15ms of actual delay. Combined with network jitter, a "bit 1" delay can easily reach 20–30ms, dangerously close to the 30ms threshold.

### 4. No Error Detection

A single misclassified bit silently corrupts the entire decoded message. There are no checksums, parity bits, or error-correcting codes. The decoder cannot distinguish a correct decode from a garbled one.

### 5. Fixed Threshold Doesn't Adapt

The 0.03s midpoint is hardcoded and doesn't adapt to actual network/system conditions. On a loaded system or high-latency connection, all delays shift upward, but the threshold stays fixed.

### 6. Delays List Not Reset on Re-encode

Setting `message` twice on the same `TemporalCloakEncoding` instance appends delays from both messages because `_delays` is never cleared.

**File:** `TemporalCloakEncoding.py` — `generate_delays()` appends to `self._delays` without clearing first

### 7. Chunk Byte Counting Bug (Demo 2)

`temporal_cloak_cli_decoder.py` line 17 always adds `CHUNK_SIZE_TORNADO` (256) even for the final smaller chunk. This overcounts total bytes received.

### 8. No Bit Alignment Check

The decoder converts bits to bytes via `tobytes()` without checking the bit count is a multiple of 8. Non-aligned messages silently lose trailing bits through zero-padding.

---

## Proposed Changes

### Phase 1: Critical Fixes (Highest Impact)

#### 1a. Append End Boundary in Encoding

**File:** `TemporalCloakEncoding.py`

In the `message` setter, after `prepend(BOUNDARY_BITS)`, add `append(BOUNDARY_BITS)`. The message format becomes:

```
[0xFF00] [message bits] [0xFF00]
```

Also guard `display_completed()` in `TemporalCloakDecoding.py` against empty messages (from double-boundaries between looped messages in Demo 1).

#### 1b. Fix First-Bit Handling in Demo 1

**Files:** `demo1_server.py`, `demo1_client.py`

Server: receive first byte, THEN call `start_timer()`. Remove the `mark_time()` call on the throwaway byte.

```python
# Current (broken):
cloak.start_timer()
receive_byte(client_sock)   # throwaway
cloak.mark_time()            # records garbage bit!

# Fixed:
receive_byte(client_sock)   # throwaway
cloak.start_timer()          # timer starts AFTER connection settled
```

Client: send a sync byte + 0.1s pause before the encoded message loop, so the server has something to discard and establish its timing baseline.

#### 1c. Fix First-Bit Handling in Demo 2

**Files:** `temporal_cloak_web_demo.py`, `temporal_cloak_cli_decoder.py`

Server: send the first chunk without any delay (sync chunk), then apply encoded delays from the second chunk onward.

Client: call `start_timer()` after receiving the first chunk. Start `mark_time()` from the second chunk.

```python
first_chunk = True
for chunk in response.iter_content(chunk_size=CHUNK_SIZE_TORNADO):
    if chunk:
        total_bytes += len(chunk)  # also fixes counting bug
        if first_chunk:
            cloak.start_timer()
            first_chunk = False
        elif not cloak.completed:
            cloak.mark_time()
```

#### 1d. Fix Delays List Reset

**File:** `TemporalCloakEncoding.py`

Clear `self._delays = []` in the `message` setter before calling `generate_delays()`.

#### 1e. Fix Chunk Byte Counting

**File:** `temporal_cloak_cli_decoder.py`

Change `total_bytes += TemporalCloakConst.CHUNK_SIZE_TORNADO` to `total_bytes += len(chunk)`.

#### 1f. Add Bit Alignment Validation

**File:** `TemporalCloakDecoding.py`

In `bits_to_message()`, after extracting the message bits between boundaries, check `len(message) % 8 != 0` and log a warning. This makes corruption detectable rather than silent.

---

### Phase 2: Timing Robustness

#### 2a. Widen Delay Gap

**File:** `TemporalCloakConst.py`

```python
# Current:
BIT_0_TIME_DELAY = 0.05
MIDPOINT_TIME = 0.03

# Proposed:
BIT_0_TIME_DELAY = 0.10
MIDPOINT_TIME = 0.05
```

This doubles the margin for bit classification. Even with 20ms of jitter on bit-1 delays, there's still 30ms of headroom before the threshold.

**Trade-off:** Messages with many zero-bits take ~2x longer to transmit.

#### 2b. Adaptive Threshold Calibration

**File:** `TemporalCloakDecoding.py`

The boundary marker `0xFF00` is a known calibration preamble: 8 ones followed by 8 zeros. After receiving 16 bits, compute the actual average delay for each group and set the threshold to their midpoint:

```python
def calibrate_from_boundary(self):
    ones_delays = self._time_delays[0:8]   # 0xFF = 8 ones
    zeros_delays = self._time_delays[8:16] # 0x00 = 8 zeros
    avg_one = sum(ones_delays) / len(ones_delays)
    avg_zero = sum(zeros_delays) / len(zeros_delays)
    self._adaptive_threshold = (avg_one + avg_zero) / 2.0
    # Re-classify all bits using calibrated threshold
```

This automatically compensates for network conditions and system load. Depends on Phase 1 first-bit fixes being in place so the boundary preamble contains clean calibration data.

#### 2c. Confidence Scoring

**File:** `TemporalCloakDecoding.py`

Track how close each measured delay is to the threshold. Flag low-confidence bits for diagnostics:

```python
distance = abs(delay - threshold)
confidence = min(distance / threshold, 1.0)  # 0.0 = right on threshold
```

Useful as a diagnostic tool — when combined with a checksum (Phase 3), low-confidence bits point to likely error locations.

---

### Phase 3: Error Detection

#### 3a. Add XOR Checksum

**Files:** `TemporalCloakEncoding.py`, `TemporalCloakDecoding.py`

Encoder: compute 8-bit XOR checksum of all message bytes, append as 8 bits before the end boundary.

```
[0xFF00] [message bits] [8-bit XOR checksum] [0xFF00]
```

Decoder: extract the last 8 bits before the end boundary as the checksum, recompute from the message bytes, compare. Report corruption on mismatch.

```python
# Encoding:
checksum = 0
for byte in self._message_encoded:
    checksum ^= byte
checksum_bits = BitArray(uint=checksum, length=8)

# Decoding:
message_bits = extracted[:-8]
checksum_received = extracted[-8:].uint
computed = 0
for byte in message_bits.tobytes():
    computed ^= byte
valid = (computed == checksum_received)
```

#### 3b. Boundary Collision Guard

**File:** `TemporalCloakEncoding.py`

Add an assertion in `encode_message()` that all bytes are < 0x80. Since the messages are ASCII-only, `0xFF` can never appear, so the boundary pattern `0xFF00` cannot collide with message content. The assertion makes this guarantee explicit and guards against future changes.

---

### Tests to Add

**File:** `test.py`

| Test | What it verifies |
|------|-----------------|
| End boundary present | Encoded message has both start and end `0xFF00` |
| Single message completes | Feed `[boundary][msg][boundary]` delays into decoder, verify `completed=True` |
| Empty message between boundaries | Double-boundary handled gracefully (no crash, no display) |
| Bit alignment warning | Non-multiple-of-8 bits between boundaries produces warning |
| Checksum validation | Encode with checksum, verify decoder validates correctly |
| Checksum detects corruption | Flip a bit in encoded message, verify decoder flags it |
| Adaptive threshold | Feed delays with known jitter offsets, verify correct classification after calibration |
| Delays list reset | Set message twice on same encoder, verify delays are only for second message |

---

## Files to Modify

| File | Changes |
|------|---------|
| `TemporalCloakConst.py` | Wider delay gap |
| `TemporalCloakEncoding.py` | End boundary, reset delays bug, checksum, boundary guard |
| `TemporalCloakDecoding.py` | Empty message guard, adaptive threshold, confidence scoring, checksum validation, bit alignment check |
| `demo1_server.py` | Fix first-bit timing |
| `demo1_client.py` | Add sync byte |
| `temporal_cloak_web_demo.py` | Sync first chunk |
| `temporal_cloak_cli_decoder.py` | Skip first chunk timing, fix byte counting |
| `test.py` | New tests for all changes |

## Verification

1. Run `python test.py` — all existing + new tests pass
2. Demo 1: start server, start client, send "Hello World" — should decode correctly with `completed=True`
3. Demo 2: start server, fetch with client — quote should decode correctly
4. Jitter test: manually add +/-10ms noise to test delays, verify adaptive threshold still classifies correctly
