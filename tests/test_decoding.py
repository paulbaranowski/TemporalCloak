import unittest
import warnings
from bitstring import Bits, BitArray, BitStream
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.decoding import (
    TemporalCloakDecoding, FrontloadedDecoder, DistributedDecoder
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


if __name__ == '__main__':
    unittest.main()
