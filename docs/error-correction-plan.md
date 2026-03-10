# Error Correction Plan: Carry Cap + Low-Confidence Bit Correction

## Problem Statement

Benchmark analysis (3 frontloaded runs, seed 42) revealed **8 bit errors** across 150 characters with two distinct root causes:

### Cause 1: Carry-Forward Overflow (3/8 errors)

The carry-forward mechanism (`_apply_carry`) caps delays at `max_expected_delay` (0.33s) and carries excess forward. When a 0-bit delay is massively oversized (~0.50s), the carry bleeds into the next bit:

```
Gap N:   raw=0.491s → capped at 0.33s → carry=0.161s
Gap N+1: raw=0.0002s (clean 1-bit) + carry=0.161s = 0.162s > threshold=0.155s → WRONG
```

The carry from one oversized delay is large enough to flip a perfectly clean short delay above the threshold. All 3 carry-overflow errors followed 0-bit delays that were 160-180ms above the cap.

### Cause 2: Near-Threshold Jitter (5/8 errors)

A 0-bit delay (expected ~0.30s) arrives shortened to 0.11-0.15s by network conditions, landing below the ~0.155s threshold. These are genuine delivery shortfalls from TCP buffering or TLS record batching.

### Key Observation

Every misclassified bit had **confidence < 0.30** (most < 0.10). The confidence scoring system already identifies these errors — it just doesn't act on the information.

---

## Option 1: Cap the Carry Amount

### Goal

Prevent carry from accumulating enough to flip a subsequent clean bit.

### Current Behavior

```python
# decoding.py:37-51
def _apply_carry(self, delay: float) -> float:
    if not self._carry_forward_enabled:
        return delay
    corrected = delay + self._carry
    if corrected > self._max_expected_delay:
        self._carry = corrected - self._max_expected_delay  # unbounded accumulation
        corrected = self._max_expected_delay
    else:
        self._carry = 0.0
    return corrected
```

`_max_expected_delay` is `BIT_0_TIME_DELAY * 1.1 = 0.33s`. Any delay above this (e.g. 0.50s) produces carry of 0.17s — which exceeds the threshold of ~0.155s.

### Proposed Change

Add a `max_carry` cap so carry can never exceed a fraction of the threshold. This preserves carry's jitter-smoothing benefit for small overruns while preventing it from flipping subsequent bits.

#### File: `temporal_cloak/decoding.py`

**`__init__`** — add `max_carry_fraction` parameter:

```python
def __init__(self, debug=False, carry_forward=True, max_delay_margin=1.1,
             max_carry_fraction=0.5):
    # ... existing init ...
    self._max_carry_fraction = max_carry_fraction
```

**`_apply_carry`** — clamp carry to fraction of threshold:

```python
def _apply_carry(self, delay: float) -> float:
    if not self._carry_forward_enabled:
        return delay
    corrected = delay + self._carry
    if corrected > self._max_expected_delay:
        self._carry = corrected - self._max_expected_delay
        # Cap carry so it can never exceed max_carry_fraction of the threshold
        max_carry = self.threshold * self._max_carry_fraction
        if self._carry > max_carry:
            self._carry = max_carry
        corrected = self._max_expected_delay
    else:
        self._carry = 0.0
    return corrected
```

With `max_carry_fraction=0.5` and threshold ~0.155s, carry is capped at ~0.078s. A clean 1-bit delay of 0.0002s + 0.078s = 0.078s — safely below threshold. The carry cap absorbs the jitter without corrupting the next bit.

#### Propagation

The `max_carry_fraction` parameter needs to be threaded through:

- `FrontloadedDecoder.__init__` (line 252)
- `DistributedDecoder.__init__` (line 287)
- `AutoDecoder.__init__` (line 371) — stored and passed when creating the delegate

#### Tests to add (`tests/test_decoding.py`)

1. **`test_carry_cap_prevents_flip`**: Delay sequence `[0.001, 0.50, 0.001]`. Without cap: carry=0.17, 0.001+0.17=0.171 > threshold → wrong. With cap (0.5): carry capped at 0.078, 0.001+0.078=0.079 < threshold → correct.

2. **`test_carry_cap_preserves_small_carry`**: Delay sequence with modest overrun (e.g. 0.35s, carry=0.02). Verify carry is not capped (0.02 < 0.078) and behavior is identical to current.

3. **`test_carry_cap_default_value`**: Verify default `max_carry_fraction=0.5`.

### Risk Assessment

- **Low risk**: Carry capping is strictly more conservative than the current behavior. It can only reduce carry, never increase it.
- **Edge case**: If two consecutive 0-bit delays are both slightly oversized, the uncapped carry helps absorb the drift. With the cap, small timing drift may accumulate. The 0.5 fraction should be generous enough to handle this — it allows up to ~78ms of carry, while normal 0-bit jitter is typically < 30ms.

---

## Option 2: Low-Confidence Bit Correction

### Goal

After decoding completes (or fails), re-examine bits with very low confidence scores and try flipping them to see if the message improves.

### Design

This is a **post-decode correction pass** that runs after the normal streaming decode finishes. It does not change the real-time decode behavior.

#### Strategy

When a message is decoded but the checksum fails (or when decode doesn't complete), identify the lowest-confidence bits and try flipping them:

1. Collect all (bit_index, confidence) pairs from the decoded stream
2. Filter to bits with confidence below a threshold (e.g. < 0.15)
3. Sort by confidence ascending (worst first)
4. Try flipping each one individually and re-decoding
5. If any single flip produces a valid checksum, accept that correction
6. If no single flip works, try pairs of flips (limited to top-N lowest confidence)

#### File: `temporal_cloak/decoding.py`

Add a new method to `TemporalCloakDecoding`:

```python
def try_correct_low_confidence_bits(self, max_flips=5, confidence_threshold=0.15):
    """Attempt to correct the message by flipping low-confidence bits.

    Returns (corrected_message, flipped_indices) if successful, or (None, []) if not.
    """
    # Identify candidate bits to flip (low confidence, within message payload)
    candidates = [
        (i, conf) for i, conf in enumerate(self._confidence_scores)
        if conf < confidence_threshold
    ]
    candidates.sort(key=lambda x: x[1])  # lowest confidence first
    candidates = candidates[:max_flips]

    if not candidates:
        return None, []

    original_bits = self._bits.copy()

    # Try single flips
    for bit_idx, conf in candidates:
        self._bits = original_bits.copy()
        self._bits.invert(bit_idx)
        msg, completed, _ = self.bits_to_message()
        if completed and self._checksum_valid:
            return msg, [bit_idx]

    # Try pairs of flips
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            self._bits = original_bits.copy()
            self._bits.invert(candidates[i][0])
            self._bits.invert(candidates[j][0])
            msg, completed, _ = self.bits_to_message()
            if completed and self._checksum_valid:
                return msg, [candidates[i][0], candidates[j][0]]

    # Restore original bits
    self._bits = original_bits
    return None, []
```

#### Integration with `AutoDecoder`

Add a wrapper in `AutoDecoder`:

```python
def try_correction(self, max_flips=5, confidence_threshold=0.15):
    """Attempt low-confidence bit correction on the delegate decoder."""
    if not self._delegate:
        return None, []
    return self._delegate.try_correct_low_confidence_bits(
        max_flips=max_flips,
        confidence_threshold=confidence_threshold
    )
```

#### Integration with CLI (`temporal_cloak/cli.py`)

In `DecodeSession.run()`, after the streaming loop, if checksum fails or decode is incomplete:

```python
# After streaming completes, in run():
if self._cloak.message_complete and not self._cloak.checksum_valid:
    corrected, flipped = self._cloak.try_correction()
    if corrected:
        # Show corrected message
```

#### Integration with benchmark (`scripts/benchmark.py`)

In `decode_link()`, after streaming, attempt correction and record results:

```python
# After streaming, before returning results:
corrected_message = None
flipped_indices = []
if not decoder.checksum_valid:
    corrected_message, flipped_indices = decoder.try_correct_low_confidence_bits()

return {
    # ... existing fields ...
    "corrected_message": corrected_message,
    "flipped_indices": flipped_indices,
}
```

#### Important constraint: bit index mapping

The confidence scores and bit indices in `_confidence_scores` correspond to the raw timing gaps, which map 1:1 to bits in `_bits` for frontloaded mode. For distributed mode, only selected gap positions carry bits, so the mapping is already handled by the decoder — `_confidence_scores` only contains entries for real-bit gaps.

The `bits_to_message()` method works on the `_bits` stream, so flipping a bit in `_bits` and re-calling `bits_to_message()` correctly re-decodes with the flipped bit.

#### Tests to add

1. **`test_single_flip_correction`**: Encode a message, simulate one low-confidence bit flip (inject a delay near threshold), verify `try_correct_low_confidence_bits` finds and fixes it.

2. **`test_double_flip_correction`**: Two low-confidence errors, verify pair-flip correction works.

3. **`test_no_correction_needed`**: All bits high confidence, verify returns `(None, [])`.

4. **`test_correction_respects_max_flips`**: Inject 10 errors but set `max_flips=3`, verify only 3 candidates are tried.

5. **`test_correction_does_not_corrupt`**: Verify that if no correction succeeds, the original bits are restored unchanged.

### Risk Assessment

- **Low risk for correctness**: The correction only accepts a result if the checksum passes, so it cannot introduce a worse message. The checksum is an 8-bit XOR, giving a 1/256 chance of a false positive per flip attempt.
- **Performance**: For N candidates, single flips = N attempts, pair flips = N*(N-1)/2 attempts. With `max_flips=5`, worst case is 5 + 10 = 15 re-decode attempts. Each re-decode is just bit manipulation (microseconds), not network I/O.
- **False positive risk**: The 8-bit XOR checksum has a 1/256 (~0.4%) false positive rate per attempt. With 15 attempts, the cumulative false positive probability is ~5.7%. This is acceptable for a "best effort" correction, but the UI should indicate when a correction was applied.

---

## Implementation Order

**Phase 1: Carry Cap (Option 1)**
- Modify `_apply_carry` in `decoding.py`
- Thread parameter through decoder constructors
- Add tests
- Run benchmark to measure improvement

**Phase 2: Low-Confidence Correction (Option 2)**
- Add `try_correct_low_confidence_bits` to `TemporalCloakDecoding`
- Add `try_correction` to `AutoDecoder`
- Integrate into CLI and benchmark
- Add tests
- Run benchmark to measure improvement

Phase 1 should be done first because it reduces the number of errors that Phase 2 needs to correct. The carry cap eliminates the carry-overflow error class entirely, leaving only near-threshold jitter errors for the correction pass.

---

## Expected Impact

Based on the 3-run benchmark analysis:

| Metric | Before | After Phase 1 | After Phase 2 |
|--------|--------|---------------|---------------|
| Total bit errors | 8 | ~5 (carry-overflow eliminated) | ~0-1 (correction fixes near-threshold) |
| Exact match rate | 0/3 (0%) | ~1/3 (33%) | ~2-3/3 (67-100%) |
| Carry-overflow errors | 3 | 0 | 0 |
| Near-threshold errors | 5 | 5 | ~0-1 |
