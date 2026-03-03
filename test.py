import unittest
import warnings
from TemporalCloakConst import TemporalCloakConst
from TemporalCloakDecoding import TemporalCloakDecoding
from TemporalCloakEncoding import TemporalCloakEncoding
from bitstring import Bits, BitArray, BitStream


def _checksum(msg_bytes):
    """Helper: compute 8-bit XOR checksum."""
    c = 0
    for b in msg_bytes:
        c ^= b
    return c


class TestTemporalCloakDecoding(unittest.TestCase):

    def setUp(self):
        self.decoding = TemporalCloakDecoding()
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
        enc = TemporalCloakEncoding()
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
        enc = TemporalCloakEncoding()
        enc.message = "test"
        decoder = TemporalCloakDecoding()
        # Feed all bits from the encoder directly into the decoder
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        result, completed, end_pos = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "test")


class TestEmptyMessageGuard(unittest.TestCase):
    """Double-boundary (empty message) should be handled gracefully."""

    def test_empty_message_between_boundaries(self):
        decoder = TemporalCloakDecoding()
        # Two boundaries back to back: [0xFF00][0xFF00]
        bits = BitStream(TemporalCloakConst.BOUNDARY_BITS + TemporalCloakConst.BOUNDARY_BITS)
        decoder._bits = bits
        result, completed, end_pos = decoder.bits_to_message()
        self.assertTrue(completed)
        # Should decode to empty string, and display_completed should not crash
        self.assertEqual(result, "")
        decoder.display_completed(result)  # should not raise


class TestBitAlignment(unittest.TestCase):
    """Non-multiple-of-8 bits between boundaries should produce a warning."""

    def test_misaligned_bits_warn(self):
        decoder = TemporalCloakDecoding()
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
        enc = TemporalCloakEncoding()
        enc.message = "hello"
        decoder = TemporalCloakDecoding()
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "hello")
        self.assertTrue(decoder.checksum_valid)

    def test_checksum_detects_corruption(self):
        enc = TemporalCloakEncoding()
        enc.message = "hello"
        # Flip a bit in the message payload (after start boundary)
        corrupted = BitArray(enc._message_bits_padded)
        boundary_len = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        flip_pos = boundary_len + 3  # flip a bit inside the payload
        corrupted.invert(flip_pos)
        decoder = TemporalCloakDecoding()
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
        enc = TemporalCloakEncoding()
        enc.message = "AB"
        decoder = TemporalCloakDecoding()

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


class TestDelaysReset(unittest.TestCase):
    """Setting message twice should only produce delays for the second message."""

    def test_delays_reset_on_reencode(self):
        enc = TemporalCloakEncoding()
        enc.message = "first"
        first_delays_len = len(enc.delays)
        enc.message = "hi"
        # Delays should correspond only to "hi" (not accumulated with "first")
        expected_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS)) * 2 + len(BitArray(b'hi')) + 8  # +8 for checksum
        self.assertEqual(len(enc.delays), expected_bits)
        self.assertNotEqual(len(enc.delays), first_delays_len + expected_bits)


class TestBoundaryCollisionGuard(unittest.TestCase):
    """encode_message should assert on non-ASCII bytes."""

    def test_ascii_passes(self):
        success, encoded = TemporalCloakEncoding.encode_message("hello")
        self.assertTrue(success)
        self.assertEqual(encoded, b"hello")

    def test_non_ascii_fails(self):
        success, encoded = TemporalCloakEncoding.encode_message("caf\u00e9")
        self.assertFalse(success)


if __name__ == '__main__':
    unittest.main()
