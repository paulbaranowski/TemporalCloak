import unittest
from bitstring import BitArray
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.encoding import TemporalCloakEncoding


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


class TestBitsRequired(unittest.TestCase):
    """Tests for the bits_required / min_image_size / validate / max_message_len helpers."""

    def test_bits_required_empty_message(self):
        # 0 chars: boundary(16) + 0 payload + checksum(8) + boundary(16) = 40
        self.assertEqual(TemporalCloakEncoding.bits_required(0), 40)

    def test_bits_required_single_char(self):
        # 1 char = 8 bits payload → 40 + 8 = 48
        self.assertEqual(TemporalCloakEncoding.bits_required(1), 48)

    def test_bits_required_matches_actual_delays(self):
        enc = TemporalCloakEncoding()
        enc.message = "hello"
        self.assertEqual(TemporalCloakEncoding.bits_required(5), len(enc.delays))

    def test_min_image_size(self):
        # For 1 char (48 bits), need 49 chunks; min bytes = 48*256 + 1 = 12289
        self.assertEqual(TemporalCloakEncoding.min_image_size(1, chunk_size=256), 48 * 256 + 1)

    def test_validate_image_size_exact_fit(self):
        min_size = TemporalCloakEncoding.min_image_size(5)
        self.assertTrue(TemporalCloakEncoding.validate_image_size(min_size, 5))

    def test_validate_image_size_too_small(self):
        min_size = TemporalCloakEncoding.min_image_size(5)
        self.assertFalse(TemporalCloakEncoding.validate_image_size(min_size - 1, 5))

    def test_validate_image_size_larger_is_ok(self):
        min_size = TemporalCloakEncoding.min_image_size(5)
        self.assertTrue(TemporalCloakEncoding.validate_image_size(min_size * 2, 5))

    def test_max_message_len_roundtrip(self):
        # Use a large enough image so max_len > 0
        image_size = 50000
        max_len = TemporalCloakEncoding.max_message_len(image_size)
        self.assertGreater(max_len, 0)
        self.assertTrue(TemporalCloakEncoding.validate_image_size(image_size, max_len))
        self.assertFalse(TemporalCloakEncoding.validate_image_size(image_size, max_len + 1))

    def test_max_message_len_tiny_image(self):
        # An image of 1 chunk (256 bytes) has 0 delay slots → can't carry anything
        self.assertEqual(TemporalCloakEncoding.max_message_len(256, chunk_size=256), 0)

    def test_max_message_len_too_small_for_overhead(self):
        # 10000 bytes = ceil(10000/256)=40 chunks = 39 slots, but overhead is 40 bits
        self.assertEqual(TemporalCloakEncoding.max_message_len(10000), 0)


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
