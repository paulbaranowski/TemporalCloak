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
