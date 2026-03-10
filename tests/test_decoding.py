import unittest
import warnings
from bitstring import Bits, BitArray, BitStream
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.decoding import (
    TemporalCloakDecoding, FrontloadedDecoder, DistributedDecoder,
    StreamingFrontloadedDecoder
)
from temporal_cloak.encoding import FrontloadedEncoder, DistributedEncoder


def _checksum(msg_bytes):
    """Helper: compute 8-bit XOR checksum."""
    c = 0
    for b in msg_bytes:
        c ^= b
    return c


class TestTemporalCloakDecoding(unittest.TestCase):

    def setUp(self):
        self.decoding = FrontloadedDecoder()
        # "hello" with checksum (0x62) + boundary markers, plus trailing bytes
        # Format: [0xFF00][68656c6c6f][62][FF00][6865]
        self.test_bits = BitStream('0xFF0068656c6c6f62FF006865')
        self.test_message = 'hello'

    def test_add_bit(self):
        self.decoding.add_bit(1)
        self.assertEqual(self.decoding.bits, BitStream('0b1'))

    def test_add_bit_by_delay(self):
        self.decoding.add_bit_by_delay(TemporalCloakConst.BIT_1_TIME_DELAY)
        self.assertEqual(self.decoding.bits, BitStream('0b1'))
        self.decoding.add_bit_by_delay(TemporalCloakConst.BIT_0_TIME_DELAY)
        self.assertEqual(self.decoding.bits, BitStream('0b10'))

    def test_find_boundary(self):
        result = self.decoding.find_boundary(self.test_bits)
        self.assertEqual(result, 0)

    def test_bits_to_message(self):
        self.decoding._bits = self.test_bits
        result, completed, end_pos = self.decoding.bits_to_message()
        self.assertEqual(result, self.test_message)
        self.assertTrue(completed)

    def test_jump_to_next_message(self):
        self.decoding._bits = self.test_bits
        self.decoding.bits_to_message()
        self.decoding.jump_to_next_message()
        self.assertEqual(self.decoding.bits, BitStream('0xFF006865'))


class TestFindBoundary(unittest.TestCase):
    def setUp(self):
        self.bits_with_boundary = BitArray('0b0101010101') + BitArray(TemporalCloakConst.BOUNDARY_BITS) + BitArray('0b0101010101')
        self.bits_with_two_boundaries = BitArray('0b0101010101') + BitArray(TemporalCloakConst.BOUNDARY_BITS) + BitArray('0b0101010101') + BitArray(TemporalCloakConst.BOUNDARY_BITS)
        self.bits_without_boundary = BitArray('0b0101010101010101010101010101')

    def test_boundary_found(self):
        result = TemporalCloakDecoding.find_boundary(self.bits_with_boundary)
        self.assertEqual(result, 10)

    def test_boundary_not_found(self):
        result = TemporalCloakDecoding.find_boundary(self.bits_without_boundary)
        self.assertIsNone(result)

    def test_two_boundaries(self):
        first = TemporalCloakDecoding.find_boundary(self.bits_with_two_boundaries)+1
        second = TemporalCloakDecoding.find_boundary(self.bits_with_two_boundaries, first)
        # 10 + 16 + 10 + 16 = 52
        self.assertEqual(second, 36)

    def test_fuzzy_finds_corrupted_boundary(self):
        """Fuzzy search finds a boundary with 1-2 bit errors."""
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)  # 0xFF00
        corrupted = BitArray(boundary)
        corrupted.invert(12)  # flip one bit
        # Use all-zero padding (far from 0xFF00) to avoid false fuzzy matches
        padding = BitArray(16)
        bits = BitStream(padding + corrupted + padding)
        # Exact search should miss it
        self.assertIsNone(TemporalCloakDecoding.find_boundary(bits))
        # Fuzzy search should find it at position 16
        result = TemporalCloakDecoding.find_boundary_fuzzy(bits, max_errors=2)
        self.assertEqual(result, 16)

    def test_fuzzy_rejects_too_many_errors(self):
        """Fuzzy search rejects a boundary with more errors than max_errors."""
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        corrupted = BitArray(boundary)
        corrupted.invert(0)
        corrupted.invert(5)
        corrupted.invert(12)  # 3 bit errors
        bits = BitStream(BitArray('0b0101010101') + corrupted + BitArray('0b0101010101'))
        result = TemporalCloakDecoding.find_boundary_fuzzy(bits, max_errors=2)
        self.assertIsNone(result)

    def test_corrupted_end_boundary_still_completes(self):
        """Message with a corrupted end boundary should still complete via fuzzy match."""
        enc = FrontloadedEncoder()
        enc.message = "ok"
        bits = BitArray(enc._message_bits_padded)
        # Corrupt 1 bit in the end boundary (last 16 bits)
        bits.invert(len(bits) - 5)

        decoder = FrontloadedDecoder()
        for bit in bits:
            decoder.add_bit(int(bit))

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "ok")
        self.assertTrue(decoder.checksum_valid)

    def test_corrupted_start_boundary_still_completes(self):
        """Message with a corrupted start boundary should still complete via fuzzy match."""
        enc = FrontloadedEncoder()
        enc.message = "ok"
        bits = BitArray(enc._message_bits_padded)
        # Corrupt 1 bit in the start boundary (first 16 bits)
        bits.invert(3)

        decoder = FrontloadedDecoder()
        for bit in bits:
            decoder.add_bit(int(bit))

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "ok")
        self.assertTrue(decoder.checksum_valid)


class TestEndBoundary(unittest.TestCase):
    """Verify that the encoder produces both start and end boundary markers."""

    def test_encoded_message_has_both_boundaries(self):
        enc = FrontloadedEncoder()
        enc.message = "hi"
        bits = enc._message_bits_padded
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        # Find first boundary
        pos1 = bits.find(boundary)
        self.assertTrue(len(pos1) > 0, "Start boundary not found")
        # Find second boundary after first
        pos2 = bits.find(boundary, pos1[0] + 1)
        self.assertTrue(len(pos2) > 0, "End boundary not found")


class TestSingleMessageCompletes(unittest.TestCase):
    """A single encoded message should decode as completed."""

    def test_single_message_completes(self):
        enc = FrontloadedEncoder()
        enc.message = "test"
        decoder = FrontloadedDecoder()
        # Feed all bits from the encoder directly into the decoder
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        result, completed, end_pos = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "test")


class TestEmptyMessageGuard(unittest.TestCase):
    """Double-boundary (empty message) should be handled gracefully."""

    def test_empty_message_between_boundaries(self):
        decoder = FrontloadedDecoder()
        # Two boundaries back to back: [0xFF00][0xFF00]
        bits = BitStream(TemporalCloakConst.BOUNDARY_BITS + TemporalCloakConst.BOUNDARY_BITS)
        decoder._bits = bits
        result, completed, end_pos = decoder.bits_to_message()
        self.assertTrue(completed)
        # Should decode to empty string, and on_completed should not crash
        self.assertEqual(result, "")
        decoder.on_completed(result)  # should not raise


class TestBitAlignment(unittest.TestCase):
    """Non-multiple-of-8 bits between boundaries should produce a warning."""

    def test_misaligned_bits_warn(self):
        decoder = FrontloadedDecoder()
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        # 5 bits of payload (not multiple of 8) + 8-bit checksum
        payload = BitArray('0b10101')
        checksum = BitArray(uint=0, length=8)
        bits = BitStream(boundary + payload + checksum + boundary)
        decoder._bits = bits
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            decoder.bits_to_message()
            alignment_warns = [x for x in w if "not aligned" in str(x.message)]
            self.assertTrue(len(alignment_warns) > 0, "Expected bit alignment warning")


class TestXORChecksum(unittest.TestCase):
    """Verify XOR checksum encoding and decoding."""

    def test_checksum_valid_on_good_message(self):
        enc = FrontloadedEncoder()
        enc.message = "hello"
        decoder = FrontloadedDecoder()
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "hello")
        self.assertTrue(decoder.checksum_valid)

    def test_checksum_detects_corruption(self):
        enc = FrontloadedEncoder()
        enc.message = "hello"
        # Flip a bit in the message payload (after start boundary)
        corrupted = BitArray(enc._message_bits_padded)
        boundary_len = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        flip_pos = boundary_len + 3  # flip a bit inside the payload
        corrupted.invert(flip_pos)
        decoder = FrontloadedDecoder()
        for bit in corrupted:
            decoder.add_bit(int(bit))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result, completed, _ = decoder.bits_to_message()
            self.assertTrue(completed)
            checksum_warns = [x for x in w if "Checksum mismatch" in str(x.message)]
            self.assertTrue(len(checksum_warns) > 0, "Expected checksum mismatch warning")
        self.assertFalse(decoder.checksum_valid)

    def test_checksum_valid_survives_post_completion_calls(self):
        """After message completes, subsequent bits_to_message() calls must not
        reset checksum_valid back to None."""
        enc = FrontloadedEncoder()
        enc.message = "hello"
        decoder = FrontloadedDecoder()
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertTrue(decoder.checksum_valid)

        # Simulate post-completion chunks arriving (adds bits, re-calls decode)
        for _ in range(16):
            decoder.add_bit(0)
        result2, completed2, _ = decoder.bits_to_message()

        # checksum_valid must still be True, not reset to None
        self.assertTrue(decoder.checksum_valid)


class TestAdaptiveThreshold(unittest.TestCase):
    """Verify adaptive threshold calibrates correctly with jittery delays."""

    def test_adaptive_threshold_with_jitter(self):
        enc = FrontloadedEncoder()
        enc.message = "AB"
        decoder = FrontloadedDecoder()

        # Simulate jitter: add +/-10ms noise to each delay
        import random
        random.seed(42)
        for delay in enc.delays:
            jittered = delay + random.uniform(-0.01, 0.01)
            jittered = max(0.0, jittered)  # clamp to non-negative
            decoder.add_bit_by_delay(jittered)

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "AB")
        # Adaptive threshold should have been calibrated
        self.assertIsNotNone(decoder._adaptive_threshold)


class TestDistributedDecoder(unittest.TestCase):
    """Tests for DistributedDecoder preamble handling."""

    def test_distributed_mode_ignores_filler(self):
        """Feed all delays including filler, verify only bit-position delays are decoded."""
        import math
        enc = DistributedEncoder()
        enc.message = "AB"
        image_size = 50000
        chunk_size = 256
        delays = enc.generate_delays(image_size, chunk_size)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = DistributedDecoder(total_gaps)
        for i, delay in enumerate(delays):
            decoder.add_bit_by_delay(delay)
            decoder._gap_index += 1
            if decoder._gap_index == TemporalCloakConst.PREAMBLE_BITS and not decoder._preamble_collected:
                decoder._process_preamble()

        self.assertGreater(len(decoder.bits), 0)

    def test_distributed_mode_extracts_key_and_length(self):
        """Verify preamble parsing extracts correct key and msg_len."""
        import math
        enc = DistributedEncoder()
        enc.message = "hi"
        image_size = 50000
        chunk_size = 256
        delays = enc.generate_delays(image_size, chunk_size)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = DistributedDecoder(total_gaps)

        # Feed just the preamble bits
        for i in range(TemporalCloakConst.PREAMBLE_BITS):
            decoder.add_bit_by_delay(delays[i])
            decoder._gap_index += 1

        decoder._process_preamble()
        self.assertTrue(decoder._preamble_collected)
        self.assertIsNotNone(decoder._bit_positions)


class TestDecodingEdgeCases(unittest.TestCase):
    """Edge cases for decoding: threshold delays, calibration, empty bits, corrupted checksum."""

    # --- Delay exactly at threshold ---

    def test_delay_at_exact_threshold(self):
        """add_bit_by_delay with delay == MIDPOINT_TIME should not crash."""
        decoder = FrontloadedDecoder()
        decoder.add_bit_by_delay(TemporalCloakConst.MIDPOINT_TIME)
        # At exactly the threshold, delay <= threshold classifies as 1
        self.assertEqual(decoder.bits, BitStream('0b1'))

    def test_confidence_at_threshold_is_zero(self):
        """Confidence should be 0 when delay == threshold (equidistant)."""
        decoder = FrontloadedDecoder()
        decoder.add_bit_by_delay(TemporalCloakConst.MIDPOINT_TIME)
        self.assertAlmostEqual(decoder.confidence_scores[0], 0.0, places=5)

    # --- Calibration with identical delays ---

    def test_calibrate_identical_delays(self):
        """16 identical delays should calibrate without crash (threshold = delay value)."""
        decoder = FrontloadedDecoder()
        fixed_delay = 0.05
        for _ in range(16):
            decoder.add_bit_by_delay(fixed_delay)
        decoder.calibrate_from_boundary()
        self.assertIsNotNone(decoder._adaptive_threshold)
        self.assertAlmostEqual(decoder._adaptive_threshold, fixed_delay, places=5)

    # --- Empty bits_to_message ---

    def test_bits_to_message_with_no_bits(self):
        """bits_to_message on a fresh decoder returns empty gracefully."""
        decoder = FrontloadedDecoder()
        result, completed, end_pos = decoder.bits_to_message()
        self.assertEqual(result, "")
        self.assertFalse(completed)
        self.assertIsNone(end_pos)

    # --- Corrupted checksum ---

    def test_corrupted_checksum_detected(self):
        """Flipping a bit in the checksum region should flag checksum_valid == False."""
        enc = FrontloadedEncoder()
        enc.message = "test"
        corrupted = BitArray(enc._message_bits_padded)
        boundary_len = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        # Checksum is the last 8 bits before the end boundary
        checksum_start = len(corrupted) - boundary_len - 8
        corrupted.invert(checksum_start)  # flip first checksum bit

        decoder = FrontloadedDecoder()
        for bit in corrupted:
            decoder.add_bit(int(bit))
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertFalse(decoder.checksum_valid)
        # Message is still returned even with bad checksum
        self.assertIsInstance(result, str)

    # --- find_boundary with bits shorter than 16 ---

    def test_find_boundary_short_bits(self):
        """Bits shorter than the boundary (16 bits) should return None."""
        short_bits = BitStream('0b10101010')
        result = TemporalCloakDecoding.find_boundary(short_bits)
        self.assertIsNone(result)

    def test_find_boundary_empty_bits(self):
        """Empty bit stream should return None."""
        result = TemporalCloakDecoding.find_boundary(BitStream())
        self.assertIsNone(result)


class TestCarryForwardCompensation(unittest.TestCase):
    """Verify carry-forward delay compensation caps oversized gaps and
    redistributes excess to the next gap."""

    def test_basic(self):
        """Shifted delays: gap 2 is oversized (absorbed part of gap 3).
        Carry-forward should cap gap 2 and add excess to gap 3, classifying
        gap 3 correctly as 0."""
        decoder = FrontloadedDecoder(carry_forward=True)
        # Expected: 1, 0, 0 (delays: 0.0, 0.3, 0.3)
        # Shifted:  0.001, 0.40, 0.10
        # Without carry: 0.40 > 0.15 → 0 (ok), 0.10 < 0.15 → 1 (WRONG, should be 0)
        # With carry: 0.40 capped at 0.33, carry=0.07 (under cap of ~0.078)
        #             0.10 + 0.07 = 0.17 > 0.15 → 0 (CORRECT)
        delays = [0.001, 0.40, 0.10]
        for d in delays:
            decoder.add_bit_by_delay(d)
        # Bits should be: 1, 0, 0
        self.assertEqual(decoder.bits, BitStream('0b100'))

    def test_disabled(self):
        """Same shifted delays with carry_forward=False should use raw delays."""
        decoder = FrontloadedDecoder(carry_forward=False)
        delays = [0.001, 0.55, 0.05]
        for d in delays:
            decoder.add_bit_by_delay(d)
        # Without carry: 0.001→1, 0.55→0, 0.05→1
        self.assertEqual(decoder.bits, BitStream('0b101'))

    def test_clean_delays_unaffected(self):
        """Normal delays (no jitter) should pass through unchanged."""
        decoder = FrontloadedDecoder(carry_forward=True)
        delays = [
            TemporalCloakConst.BIT_1_TIME_DELAY,  # 0.0 → 1
            TemporalCloakConst.BIT_0_TIME_DELAY,  # 0.3 → 0
            TemporalCloakConst.BIT_1_TIME_DELAY,  # 0.0 → 1
            TemporalCloakConst.BIT_0_TIME_DELAY,  # 0.3 → 0
        ]
        for d in delays:
            decoder.add_bit_by_delay(d)
        self.assertEqual(decoder.bits, BitStream('0b1010'))
        # Carry should be zero after clean delays
        self.assertAlmostEqual(decoder._carry, 0.0)

    def test_carry_resets_on_completed(self):
        """After a full message decode, carry should reset to 0."""
        enc = FrontloadedEncoder()
        enc.message = "AB"
        decoder = FrontloadedDecoder(carry_forward=True)
        # Inject a non-zero carry
        decoder._carry = 0.1
        for delay in enc.delays:
            decoder.add_bit_by_delay(delay)
        result, completed, _ = decoder.bits_to_message()
        if completed:
            decoder.on_completed(result)
        self.assertAlmostEqual(decoder._carry, 0.0)

    def test_carry_cap_prevents_flip(self):
        """An oversized 0-bit delay should not flip the next clean 1-bit.

        Delay sequence: [0.001 (1-bit), 0.50 (huge 0-bit), 0.001 (clean 1-bit)]
        Without cap: carry=0.50-0.33=0.17 → 0.001+0.17=0.171 > threshold → wrong 0
        With cap (0.5): carry capped at ~0.078 → 0.001+0.078=0.079 < threshold → correct 1
        """
        decoder = FrontloadedDecoder(carry_forward=True)
        delays = [0.001, 0.50, 0.001]
        for d in delays:
            decoder.add_bit_by_delay(d)
        self.assertEqual(decoder.bits, BitStream('0b101'))
        # After all three delays, carry should have been consumed (added to third delay)
        self.assertAlmostEqual(decoder._carry, 0.0)

    def test_carry_cap_prevents_flip_without_cap(self):
        """Verify the uncapped behavior would have produced the wrong result."""
        decoder = FrontloadedDecoder(carry_forward=True, max_carry_fraction=100.0)
        delays = [0.001, 0.50, 0.001]
        for d in delays:
            decoder.add_bit_by_delay(d)
        # With effectively no cap, carry=0.17 flips the third bit to 0
        self.assertEqual(decoder.bits, BitStream('0b100'))

    def test_carry_cap_consecutive_oversized_delays(self):
        """Multiple consecutive oversized 0-bit delays should not accumulate
        carry beyond the cap, even when each one individually overflows."""
        decoder = FrontloadedDecoder(carry_forward=True)
        # Three oversized 0-bits in a row, then a clean 1-bit
        delays = [0.50, 0.50, 0.50, 0.001]
        for d in delays:
            decoder.add_bit_by_delay(d)
        # All oversized delays classified as 0, the clean 1-bit stays 1
        self.assertEqual(decoder.bits, BitStream('0b0001'))

    def test_carry_cap_massive_overflow(self):
        """An extremely large delay (e.g. 2.0s) should still cap carry safely."""
        decoder = FrontloadedDecoder(carry_forward=True)
        delays = [2.0, 0.001]
        for d in delays:
            decoder.add_bit_by_delay(d)
        # 2.0 → 0 (capped at 0.33, carry capped at threshold*0.5 ≈ 0.078)
        # 0.001 + 0.078 = 0.079 < threshold → 1
        self.assertEqual(decoder.bits, BitStream('0b01'))
        max_carry = decoder.threshold * decoder._max_carry_fraction
        # Carry after second delay was consumed, but verify it was clamped after first
        self.assertAlmostEqual(decoder._carry, 0.0)

    def test_carry_cap_alternating_oversized_and_clean(self):
        """Alternating oversized 0-bits and clean 1-bits — carry cap should
        protect every clean 1-bit from being flipped."""
        decoder = FrontloadedDecoder(carry_forward=True)
        # Pattern: oversized-0, clean-1, oversized-0, clean-1, oversized-0, clean-1
        delays = [0.50, 0.001, 0.50, 0.001, 0.50, 0.001]
        for d in delays:
            decoder.add_bit_by_delay(d)
        self.assertEqual(decoder.bits, BitStream('0b010101'))

    def test_carry_cap_just_below_cap_threshold(self):
        """Carry just below the cap should pass through without clamping."""
        decoder = FrontloadedDecoder(carry_forward=True)
        max_carry = decoder.threshold * decoder._max_carry_fraction
        # Construct a delay that produces carry just under the cap
        # max_expected = 0.33, so delay = 0.33 + (max_carry - 0.001) ≈ 0.407
        delay_just_under = decoder._max_expected_delay + max_carry - 0.001
        decoder.add_bit_by_delay(delay_just_under)
        # Carry should be just under the cap (not clamped)
        expected_carry = delay_just_under - decoder._max_expected_delay
        self.assertAlmostEqual(decoder._carry, expected_carry, places=5)
        self.assertLess(decoder._carry, max_carry)

    def test_carry_cap_just_above_cap_threshold(self):
        """Carry just above the cap should be clamped to exactly the cap."""
        decoder = FrontloadedDecoder(carry_forward=True)
        max_carry = decoder.threshold * decoder._max_carry_fraction
        # Delay that produces carry just over the cap
        delay_just_over = decoder._max_expected_delay + max_carry + 0.01
        decoder.add_bit_by_delay(delay_just_over)
        self.assertAlmostEqual(decoder._carry, max_carry, places=5)

    def test_carry_cap_custom_fraction(self):
        """Custom max_carry_fraction should change the cap proportionally."""
        # Very tight cap (10% of threshold)
        decoder = FrontloadedDecoder(carry_forward=True, max_carry_fraction=0.1)
        decoder.add_bit_by_delay(0.50)  # big overflow
        max_carry = decoder.threshold * 0.1
        self.assertAlmostEqual(decoder._carry, max_carry, places=5)

        # Very loose cap (90% of threshold)
        decoder2 = FrontloadedDecoder(carry_forward=True, max_carry_fraction=0.9)
        decoder2.add_bit_by_delay(0.50)  # same overflow
        max_carry2 = decoder2.threshold * 0.9
        self.assertAlmostEqual(decoder2._carry, max_carry2, places=5)

    def test_carry_cap_end_to_end_with_jitter(self):
        """Full encode/decode with simulated carry-overflow jitter pattern.
        Inject the exact error pattern from the benchmark: a 0-bit delay
        bloats to ~0.50s, stealing time from the next 1-bit gap."""
        enc = FrontloadedEncoder()
        enc.message = "OK"
        delays = list(enc.delays)

        # Find a 0-bit followed by a 1-bit and inject carry-overflow jitter
        for i in range(len(delays) - 1):
            if delays[i] > 0.1 and delays[i + 1] < 0.1:
                # Bloat the 0-bit to 0.50s (simulating TCP buffering)
                delays[i] = 0.50
                delays[i + 1] = max(0.0, delays[i + 1])
                break

        decoder = FrontloadedDecoder(carry_forward=True)
        for d in delays:
            decoder.add_bit_by_delay(d)
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "OK")

    def test_carry_cap_preserves_small_carry(self):
        """Modest overruns should carry through without being capped."""
        decoder = FrontloadedDecoder(carry_forward=True)
        # 0.35s is slightly above max_expected (0.33s), carry = 0.02
        # 0.02 < threshold*0.5 (~0.078), so carry should pass through uncapped
        delays = [0.001, 0.35, 0.13]
        for d in delays:
            decoder.add_bit_by_delay(d)
        # 0.001 → 1, 0.35 capped at 0.33 → 0 (carry=0.02), 0.13+0.02=0.15 ≤ threshold → 1
        self.assertEqual(decoder.bits, BitStream('0b101'))
        # Carry should now be 0 (it was consumed)
        self.assertAlmostEqual(decoder._carry, 0.0)

    def test_carry_cap_default_value(self):
        """Default max_carry_fraction should be 0.5."""
        decoder = FrontloadedDecoder()
        self.assertEqual(decoder._max_carry_fraction, 0.5)

    def test_end_to_end(self):
        """Encode a message, simulate jitter by shifting delay between
        adjacent gaps, decode with carry-forward, verify correct message."""
        enc = FrontloadedEncoder()
        enc.message = "Hi"
        delays = list(enc.delays)

        # Simulate TCP jitter: shift delay from gap i+1 to gap i
        # Find a pair where gap[i] is a 0-bit (0.3) followed by a 1-bit (0.0)
        # and shift some delay to make gap[i] oversized
        shift_amount = 0.15
        for i in range(len(delays) - 1):
            if delays[i] > 0.1 and delays[i + 1] < 0.1:
                delays[i] += shift_amount
                delays[i + 1] = max(0.0, delays[i + 1] - shift_amount)
                break

        decoder = FrontloadedDecoder(carry_forward=True)
        for d in delays:
            decoder.add_bit_by_delay(d)
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "Hi")


class TestLowConfidenceBitCorrection(unittest.TestCase):
    """Verify low-confidence bit correction (Option 2 from error-correction-plan)."""

    def _encode_and_corrupt(self, message, flip_positions):
        """Encode a message, flip specific bits in the payload, return the corrupted BitArray."""
        enc = FrontloadedEncoder()
        enc.message = message
        corrupted = BitArray(enc._message_bits_padded)
        boundary_len = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        for pos in flip_positions:
            corrupted.invert(boundary_len + pos)
        return corrupted

    def _build_decoder_with_low_confidence(self, corrupted_bits, low_confidence_indices):
        """Build a FrontloadedDecoder with bits injected and specific
        confidence scores set artificially low."""
        decoder = FrontloadedDecoder()
        for bit in corrupted_bits:
            decoder.add_bit(int(bit))
        # add_bit doesn't populate confidence scores, so fill them manually
        boundary_len = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        decoder._confidence_scores = [0.9] * len(corrupted_bits)
        for idx in low_confidence_indices:
            decoder._confidence_scores[boundary_len + idx] = 0.05
        return decoder

    def test_single_flip_correction(self):
        """One corrupted bit with low confidence should be corrected."""
        corrupted = self._encode_and_corrupt("hi", [3])
        decoder = self._build_decoder_with_low_confidence(corrupted, [3])

        # Verify checksum fails before correction
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            _, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertFalse(decoder.checksum_valid)

        corrected, flipped = decoder.try_correct_low_confidence_bits()
        self.assertIsNotNone(corrected)
        self.assertEqual(corrected, "hi")
        self.assertEqual(len(flipped), 1)

    def test_double_flip_correction(self):
        """Two corrupted bits with low confidence should be corrected via pair-flip."""
        corrupted = self._encode_and_corrupt("hi", [2, 5])
        decoder = self._build_decoder_with_low_confidence(corrupted, [2, 5])

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            _, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertFalse(decoder.checksum_valid)

        corrected, flipped = decoder.try_correct_low_confidence_bits()
        self.assertIsNotNone(corrected)
        self.assertEqual(corrected, "hi")
        self.assertEqual(len(flipped), 2)

    def test_triple_flip_correction(self):
        """Three corrupted bits should be corrected via triple-flip."""
        corrupted = self._encode_and_corrupt("hi", [1, 5, 10])
        decoder = self._build_decoder_with_low_confidence(corrupted, [1, 5, 10])

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            _, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertFalse(decoder.checksum_valid)

        corrected, flipped = decoder.try_correct_low_confidence_bits()
        self.assertIsNotNone(corrected)
        self.assertEqual(corrected, "hi")
        self.assertEqual(len(flipped), 3)

    def test_non_ascii_bit_error_still_completes(self):
        """A bit flip producing a non-ASCII byte should not prevent completion."""
        enc = FrontloadedEncoder()
        enc.message = "hi"
        corrupted = BitArray(enc._message_bits_padded)
        boundary_len = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        # Flip bit 7 (MSB) of first message byte: 'h' (0x68) -> 0xe8 (non-ASCII)
        corrupted.invert(boundary_len + 0)

        decoder = FrontloadedDecoder()
        for bit in corrupted:
            decoder.add_bit(int(bit))

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result, completed, _ = decoder.bits_to_message()
        # Message should still be "completed" (both boundaries found)
        self.assertTrue(completed)
        # The non-ASCII byte should appear as a surrogate-escaped char
        self.assertTrue(any(ord(c) > 127 for c in result))

    def test_no_correction_needed(self):
        """Valid message — flipping any low-confidence bit won't produce another valid checksum."""
        enc = FrontloadedEncoder()
        enc.message = "ok"
        decoder = FrontloadedDecoder()
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        decoder._confidence_scores = [0.9] * len(decoder._confidence_scores)

        corrected, flipped = decoder.try_correct_low_confidence_bits()
        self.assertIsNone(corrected)
        self.assertEqual(flipped, [])

    def test_correction_respects_max_flips(self):
        """With max_flips=2, only 2 candidates should be tried even if more are low-confidence."""
        corrupted = self._encode_and_corrupt("hi", [1, 3, 5])
        decoder = self._build_decoder_with_low_confidence(corrupted, [1, 3, 5])

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            decoder.bits_to_message()

        # With 3 flipped bits but max_flips=2, pair correction can only try
        # 2 of the 3 candidates — it may or may not find the right pair.
        # The important thing is it doesn't try all 3.
        corrected, flipped = decoder.try_correct_low_confidence_bits(max_flips=2)
        # With 3 errors and only 2 flips allowed, correction should fail
        self.assertIsNone(corrected)

    def test_correction_does_not_corrupt(self):
        """If no correction succeeds, original bits are restored unchanged."""
        corrupted = self._encode_and_corrupt("hi", [1, 3, 5, 7, 9, 11])
        decoder = self._build_decoder_with_low_confidence(corrupted, [1, 3, 5, 7, 9, 11])

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            decoder.bits_to_message()

        original_bits = BitArray(decoder._bits)

        corrected, flipped = decoder.try_correct_low_confidence_bits(max_flips=3)
        self.assertIsNone(corrected)
        self.assertEqual(flipped, [])
        # Bits should be restored to original
        self.assertEqual(BitArray(decoder._bits), original_bits)

    def test_auto_decoder_try_correction(self):
        """AutoDecoder.try_correction() delegates to the underlying decoder."""
        from temporal_cloak.decoding import AutoDecoder
        auto = AutoDecoder(total_gaps=100)
        # No delegate yet — should return (None, [])
        corrected, flipped = auto.try_correction()
        self.assertIsNone(corrected)
        self.assertEqual(flipped, [])


class TestStreamingVsImageDownload(unittest.TestCase):
    """Verify that base decoders preserve bits (image-download mode) while
    StreamingFrontloadedDecoder truncates bits (multi-message streaming)."""

    def _encode_and_feed(self, decoder):
        """Encode 'test', feed all bits into decoder, complete the message."""
        enc = FrontloadedEncoder()
        enc.message = "test"
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "test")
        return result

    def test_image_download_preserves_bits_after_completion(self):
        """FrontloadedDecoder (image-download) should NOT truncate bits after on_completed."""
        decoder = FrontloadedDecoder()
        result = self._encode_and_feed(decoder)
        bits_before = BitArray(decoder._bits)
        decoder.on_completed(result)
        # Bits should be preserved — not truncated
        self.assertEqual(BitArray(decoder._bits), bits_before)

    def test_streaming_truncates_bits_after_completion(self):
        """StreamingFrontloadedDecoder should truncate bits after on_completed."""
        decoder = StreamingFrontloadedDecoder()
        result = self._encode_and_feed(decoder)
        bits_len_before = len(decoder._bits)
        decoder.on_completed(result)
        # Bits should be truncated (shorter than before)
        self.assertLess(len(decoder._bits), bits_len_before)

    def test_correction_works_after_completion(self):
        """FrontloadedDecoder should support error correction after on_completed
        because bits are preserved."""
        enc = FrontloadedEncoder()
        enc.message = "hi"
        corrupted = BitArray(enc._message_bits_padded)
        boundary_len = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))

        # Flip one bit in the payload
        flip_pos = boundary_len + 3
        corrupted.invert(flip_pos)

        decoder = FrontloadedDecoder()
        for bit in corrupted:
            decoder.add_bit(int(bit))

        # Set up confidence scores: all high except the flipped bit
        decoder._confidence_scores = [0.9] * len(corrupted)
        decoder._confidence_scores[flip_pos] = 0.05

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            _, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertFalse(decoder.checksum_valid)

        # Complete the message — bits should be preserved
        decoder.on_completed("")

        # Error correction should still work
        corrected, flipped = decoder.try_correct_low_confidence_bits()
        self.assertIsNotNone(corrected)
        self.assertEqual(corrected, "hi")
        self.assertTrue(decoder.checksum_valid)


if __name__ == '__main__':
    unittest.main()
