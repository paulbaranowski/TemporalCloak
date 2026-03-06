import unittest
from bitstring import BitArray
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.encoding import (
    TemporalCloakEncoding, FrontloadedEncoder, DistributedEncoder
)


class TestDelaysReset(unittest.TestCase):
    """Setting message twice should only produce delays for the second message."""

    def test_delays_reset_on_reencode(self):
        enc = FrontloadedEncoder()
        enc.message = "first"
        first_delays_len = len(enc.delays)
        enc.message = "hi"
        # Delays should correspond only to "hi" (not accumulated with "first")
        expected_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS)) * 2 + len(BitArray(b'hi')) + 8  # +8 for checksum
        self.assertEqual(len(enc.delays), expected_bits)
        self.assertNotEqual(len(enc.delays), first_delays_len + expected_bits)


class TestFrontloadedBitsRequired(unittest.TestCase):
    """Tests for FrontloadedEncoder size helpers."""

    def test_bits_required_empty_message(self):
        # 0 chars: boundary(16) + 0 payload + checksum(8) + boundary(16) = 40
        self.assertEqual(FrontloadedEncoder.bits_required(0), 40)

    def test_bits_required_single_char(self):
        # 1 char = 8 bits payload -> 40 + 8 = 48
        self.assertEqual(FrontloadedEncoder.bits_required(1), 48)

    def test_bits_required_matches_actual_delays(self):
        enc = FrontloadedEncoder()
        enc.message = "hello"
        self.assertEqual(FrontloadedEncoder.bits_required(5), len(enc.delays))

    def test_min_image_size(self):
        # For 1 char (48 bits), need 49 chunks; min bytes = 48*256 + 1 = 12289
        self.assertEqual(FrontloadedEncoder.min_image_size(1, chunk_size=256), 48 * 256 + 1)

    def test_validate_image_size_exact_fit(self):
        min_size = FrontloadedEncoder.min_image_size(5)
        self.assertTrue(FrontloadedEncoder.validate_image_size(min_size, 5))

    def test_validate_image_size_too_small(self):
        min_size = FrontloadedEncoder.min_image_size(5)
        self.assertFalse(FrontloadedEncoder.validate_image_size(min_size - 1, 5))

    def test_validate_image_size_larger_is_ok(self):
        min_size = FrontloadedEncoder.min_image_size(5)
        self.assertTrue(FrontloadedEncoder.validate_image_size(min_size * 2, 5))

    def test_max_message_len_roundtrip(self):
        image_size = 50000
        max_len = FrontloadedEncoder.max_message_len(image_size)
        self.assertGreater(max_len, 0)
        self.assertTrue(FrontloadedEncoder.validate_image_size(image_size, max_len))
        self.assertFalse(FrontloadedEncoder.validate_image_size(image_size, max_len + 1))

    def test_max_message_len_tiny_image(self):
        self.assertEqual(FrontloadedEncoder.max_message_len(256, chunk_size=256), 0)

    def test_max_message_len_too_small_for_overhead(self):
        # 10000 bytes = ceil(10000/256)=40 chunks = 39 slots, but overhead is 40 bits
        self.assertEqual(FrontloadedEncoder.max_message_len(10000), 0)


class TestComputeBitPositions(unittest.TestCase):
    """Tests for compute_bit_positions used in distributed mode."""

    def test_deterministic(self):
        pos1 = DistributedEncoder.compute_bit_positions(42, 500, 100)
        pos2 = DistributedEncoder.compute_bit_positions(42, 500, 100)
        self.assertEqual(pos1, pos2)

    def test_different_keys_different_positions(self):
        pos1 = DistributedEncoder.compute_bit_positions(42, 500, 100)
        pos2 = DistributedEncoder.compute_bit_positions(99, 500, 100)
        self.assertNotEqual(pos1, pos2)

    def test_correct_count(self):
        pos = DistributedEncoder.compute_bit_positions(7, 500, 80)
        self.assertEqual(len(pos), 80)

    def test_positions_in_range(self):
        preamble = TemporalCloakConst.PREAMBLE_BITS
        pos = DistributedEncoder.compute_bit_positions(7, 500, 80)
        for p in pos:
            self.assertGreaterEqual(p, preamble)
            self.assertLess(p, 500)

    def test_positions_sorted(self):
        pos = DistributedEncoder.compute_bit_positions(7, 500, 80)
        self.assertEqual(pos, sorted(pos))


class TestGenerateDistributedDelays(unittest.TestCase):
    """Tests for DistributedEncoder.generate_delays."""

    def test_output_length(self):
        import math
        enc = DistributedEncoder()
        enc.message = "hi"
        image_size = 50000
        chunk_size = 256
        delays = enc.generate_delays(image_size, chunk_size)
        expected_gaps = math.ceil(image_size / chunk_size) - 1
        self.assertEqual(len(delays), expected_gaps)

    def test_most_delays_are_neutral(self):
        enc = DistributedEncoder()
        enc.message = "hi"
        delays = enc.generate_delays(50000)
        neutral = TemporalCloakConst.BIT_1_TIME_DELAY
        neutral_count = sum(1 for d in delays if d == neutral)
        self.assertGreater(neutral_count, len(delays) * 0.5)

    def test_delays_stored_on_instance(self):
        enc = DistributedEncoder()
        enc.message = "hi"
        delays = enc.generate_delays(50000)
        self.assertEqual(enc.delays, delays)


class TestDistributedBitsRequired(unittest.TestCase):
    """DistributedEncoder.bits_required includes 16 bits extra overhead."""

    def test_distributed_adds_overhead(self):
        frontloaded = FrontloadedEncoder.bits_required(5)
        distributed = DistributedEncoder.bits_required(5)
        self.assertEqual(distributed - frontloaded, 16)


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
