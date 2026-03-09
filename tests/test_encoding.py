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


class TestEncodingEdgeCases(unittest.TestCase):
    """Edge cases for encoding: empty messages, max length, special chars, boundary attributes."""

    # --- Empty message ---

    def test_frontloaded_empty_message(self):
        """FrontloadedEncoder with empty string produces boundary + checksum + boundary delays."""
        enc = FrontloadedEncoder()
        enc.message = ""
        expected_bits = FrontloadedEncoder.bits_required(0)  # 40
        self.assertEqual(len(enc.delays), expected_bits)

    def test_distributed_empty_message(self):
        """DistributedEncoder with empty string still produces delays."""
        enc = DistributedEncoder()
        enc.message = ""
        delays = enc.generate_delays(50000)
        self.assertGreater(len(delays), 0)

    # --- Max distributed length ---

    def test_distributed_max_length_255(self):
        """DistributedEncoder with exactly 255 ASCII chars should succeed."""
        enc = DistributedEncoder()
        enc.message = "A" * 255
        delays = enc.generate_delays(1_000_000)
        self.assertGreater(len(delays), 0)

    def test_distributed_over_max_length_raises(self):
        """DistributedEncoder with 256 chars should raise ValueError."""
        enc = DistributedEncoder()
        enc.message = "A" * 256
        with self.assertRaises(ValueError):
            enc.generate_delays(1_000_000)

    # --- Special ASCII boundary characters ---

    def test_special_ascii_chars_encode(self):
        """Characters \\x01, \\x7f, and \\x00 (null) should encode without error."""
        enc = FrontloadedEncoder()
        enc.message = "\x01\x7f\x00"
        self.assertEqual(len(enc.delays), FrontloadedEncoder.bits_required(3))

    def test_null_byte_message_roundtrip_bits(self):
        """Null byte message bits are properly formed with boundaries."""
        enc = FrontloadedEncoder()
        enc.message = "\x00"
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        pos1 = enc._message_bits_padded.find(boundary)
        self.assertTrue(len(pos1) > 0)
        pos2 = enc._message_bits_padded.find(boundary, pos1[0] + 1)
        self.assertTrue(len(pos2) > 0)

    # --- Boundary class attribute correctness ---

    def test_frontloaded_boundary_attribute(self):
        self.assertEqual(FrontloadedEncoder.BOUNDARY, TemporalCloakConst.BOUNDARY_BITS)

    def test_distributed_boundary_attribute(self):
        self.assertEqual(DistributedEncoder.BOUNDARY, TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED)


class TestChecksumProperty(unittest.TestCase):
    """The checksum property should be accessible after setting a message."""

    def test_checksum_matches_manual(self):
        enc = FrontloadedEncoder()
        enc.message = "hi"
        expected = TemporalCloakEncoding.compute_checksum(b"hi")
        self.assertEqual(enc.checksum, expected)

    def test_checksum_updates_on_new_message(self):
        enc = FrontloadedEncoder()
        enc.message = "hi"
        first = enc.checksum
        enc.message = "bye"
        self.assertEqual(enc.checksum, TemporalCloakEncoding.compute_checksum(b"bye"))
        self.assertNotEqual(enc.checksum, first)


class TestFrontloadedDebugSections(unittest.TestCase):
    """debug_sections() for FrontloadedEncoder."""

    def setUp(self):
        self.enc = FrontloadedEncoder()
        self.enc.message = "hi"
        self.sections = self.enc.debug_sections()
        self.labels = [s["label"] for s in self.sections]

    def test_section_labels(self):
        self.assertEqual(
            self.labels,
            ["start_boundary", "message", "checksum", "end_boundary"],
        )

    def test_no_distributed_sections(self):
        self.assertNotIn("dist_key", self.labels)
        self.assertNotIn("dist_msg_length", self.labels)

    def test_boundary_hex(self):
        boundary_hex = BitArray(TemporalCloakConst.BOUNDARY_BITS).hex
        self.assertEqual(self.sections[0]["hex"], boundary_hex)
        self.assertEqual(self.sections[-1]["hex"], boundary_hex)

    def test_message_text(self):
        msg_section = self.sections[1]
        self.assertEqual(msg_section["text"], "hi")
        self.assertEqual(msg_section["length"], 16)  # 2 chars * 8 bits

    def test_checksum_value(self):
        cs_section = self.sections[2]
        self.assertEqual(cs_section["value"], self.enc.checksum)

    def test_offsets_are_contiguous(self):
        for s in self.sections:
            # Each section should have offset and length
            self.assertIn("offset", s)
            self.assertIn("length", s)
        # Offsets should be monotonically increasing
        offsets = [s["offset"] for s in self.sections]
        self.assertEqual(offsets, sorted(offsets))
        # Each offset == previous offset + previous length
        for i in range(1, len(self.sections)):
            expected_offset = self.sections[i - 1]["offset"] + self.sections[i - 1]["length"]
            self.assertEqual(self.sections[i]["offset"], expected_offset)


class TestDistributedDebugSections(unittest.TestCase):
    """debug_sections() for DistributedEncoder."""

    def setUp(self):
        self.enc = DistributedEncoder()
        self.enc.message = "hi"
        self.enc.generate_delays(100_000, key=42)
        self.sections = self.enc.debug_sections()
        self.labels = [s["label"] for s in self.sections]

    def test_section_labels(self):
        self.assertEqual(
            self.labels,
            ["start_boundary", "dist_key", "dist_msg_length",
             "message", "checksum", "end_boundary"],
        )

    def test_boundary_uses_distributed_marker(self):
        boundary_hex = BitArray(TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED).hex
        self.assertEqual(self.sections[0]["hex"], boundary_hex)
        self.assertEqual(self.sections[-1]["hex"], boundary_hex)

    def test_dist_key_value(self):
        key_section = next(s for s in self.sections if s["label"] == "dist_key")
        self.assertEqual(key_section["value"], 42)
        self.assertEqual(key_section["length"], TemporalCloakConst.DIST_KEY_BITS)

    def test_dist_msg_length_value(self):
        len_section = next(s for s in self.sections if s["label"] == "dist_msg_length")
        self.assertEqual(len_section["value"], 2)  # len("hi")
        self.assertEqual(len_section["length"], TemporalCloakConst.DIST_LENGTH_BITS)

    def test_offsets_are_contiguous(self):
        for i in range(1, len(self.sections)):
            expected = self.sections[i - 1]["offset"] + self.sections[i - 1]["length"]
            self.assertEqual(self.sections[i]["offset"], expected)


class TestFrontloadedDebugSignalBits(unittest.TestCase):
    """debug_signal_bits() for FrontloadedEncoder."""

    def setUp(self):
        self.enc = FrontloadedEncoder()
        self.enc.message = "hi"
        self.signal = self.enc.debug_signal_bits()

    def test_starts_with_boundary(self):
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        self.assertEqual(self.signal[:len(boundary)], boundary)

    def test_ends_with_boundary(self):
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        self.assertEqual(self.signal[-len(boundary):], boundary)

    def test_length_matches_sections(self):
        sections = self.enc.debug_sections()
        total = sum(s["length"] for s in sections)
        self.assertEqual(len(self.signal), total)

    def test_matches_padded_bits(self):
        """Signal bits should equal _message_bits_padded for frontloaded."""
        self.assertEqual(self.signal, self.enc._message_bits_padded)


class TestDistributedDebugSignalBits(unittest.TestCase):
    """debug_signal_bits() for DistributedEncoder."""

    def setUp(self):
        self.enc = DistributedEncoder()
        self.enc.message = "hi"
        self.enc.generate_delays(100_000, key=99)
        self.signal = self.enc.debug_signal_bits()

    def test_starts_with_distributed_boundary(self):
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED)
        self.assertEqual(self.signal[:len(boundary)], boundary)

    def test_ends_with_distributed_boundary(self):
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED)
        self.assertEqual(self.signal[-len(boundary):], boundary)

    def test_contains_key_bits(self):
        """Signal bits should contain the key after the start boundary."""
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED)
        key_bits = BitArray(uint=99, length=TemporalCloakConst.DIST_KEY_BITS)
        start = len(boundary)
        end = start + TemporalCloakConst.DIST_KEY_BITS
        self.assertEqual(self.signal[start:end], key_bits)

    def test_length_matches_sections(self):
        sections = self.enc.debug_sections()
        total = sum(s["length"] for s in sections)
        self.assertEqual(len(self.signal), total)


class TestDistKeyProperty(unittest.TestCase):
    """DistributedEncoder.dist_key should reflect the key used."""

    def test_explicit_key_stored(self):
        enc = DistributedEncoder()
        enc.message = "test"
        enc.generate_delays(100_000, key=77)
        self.assertEqual(enc.dist_key, 77)

    def test_random_key_in_range(self):
        enc = DistributedEncoder()
        enc.message = "test"
        enc.generate_delays(100_000)
        self.assertGreaterEqual(enc.dist_key, 0)
        self.assertLessEqual(enc.dist_key, 255)


if __name__ == '__main__':
    unittest.main()
