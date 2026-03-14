import unittest
from bitstring import BitArray

from temporal_cloak.hamming import (
    hamming_encode_byte,
    hamming_decode_block,
    hamming_encode_message,
    hamming_decode_message,
)


class TestHammingEncodeByte(unittest.TestCase):
    """Test encoding single bytes into 12-bit Hamming codewords."""

    def test_encode_zero(self):
        result = hamming_encode_byte(0x00)
        self.assertEqual(len(result), 12)
        # All data bits are 0, so all parity bits should be 0
        self.assertEqual(result, BitArray(12))

    def test_encode_0xff(self):
        result = hamming_encode_byte(0xFF)
        self.assertEqual(len(result), 12)
        # All data bits are 1 — verify round-trip
        decoded, corrections = hamming_decode_block(result)
        self.assertEqual(decoded, 0xFF)
        self.assertEqual(corrections, 0)

    def test_all_byte_values_roundtrip(self):
        """Every possible byte value encodes and decodes correctly."""
        for val in range(256):
            encoded = hamming_encode_byte(val)
            self.assertEqual(len(encoded), 12, f"byte {val:#04x}")
            decoded, corrections = hamming_decode_block(encoded)
            self.assertEqual(decoded, val, f"byte {val:#04x}")
            self.assertEqual(corrections, 0, f"byte {val:#04x}")

    def test_encode_produces_12_bits(self):
        for val in [0, 1, 42, 127, 128, 255]:
            self.assertEqual(len(hamming_encode_byte(val)), 12)


class TestHammingSingleBitCorrection(unittest.TestCase):
    """Test that flipping any single bit in a codeword is corrected."""

    def test_correct_single_flip_all_positions(self):
        """For several byte values, flip each of the 12 positions and verify correction."""
        test_values = [0x00, 0x41, 0x55, 0xAA, 0xFF, 0x42, 0x7E]
        for val in test_values:
            encoded = hamming_encode_byte(val)
            for pos in range(12):
                corrupted = BitArray(encoded)
                corrupted.invert(pos)
                decoded, corrections = hamming_decode_block(corrupted)
                self.assertEqual(decoded, val,
                                 f"byte {val:#04x}, flipped pos {pos}")
                self.assertEqual(corrections, 1,
                                 f"byte {val:#04x}, flipped pos {pos}")

    def test_no_correction_needed_for_clean_block(self):
        encoded = hamming_encode_byte(0x42)
        decoded, corrections = hamming_decode_block(encoded)
        self.assertEqual(decoded, 0x42)
        self.assertEqual(corrections, 0)


class TestHammingTwoBitErrors(unittest.TestCase):
    """Two-bit errors are detected (nonzero syndrome) but miscorrected.

    This confirms the checksum is needed as a second validation layer.
    """

    def test_two_bit_error_miscorrects(self):
        """Flipping 2 bits produces a nonzero syndrome but the wrong byte."""
        val = 0x41  # 'A'
        encoded = hamming_encode_byte(val)
        corrupted = BitArray(encoded)
        corrupted.invert(2)  # flip data bit d1
        corrupted.invert(4)  # flip data bit d2
        decoded, corrections = hamming_decode_block(corrupted)
        # The decoder thinks it corrected 1 bit, but the result is wrong
        self.assertNotEqual(decoded, val)


class TestHammingDecodeBlockValidation(unittest.TestCase):
    """Test input validation."""

    def test_wrong_block_size_raises(self):
        with self.assertRaises(ValueError):
            hamming_decode_block(BitArray(8))
        with self.assertRaises(ValueError):
            hamming_decode_block(BitArray(16))


class TestHammingEncodeDecodeMessage(unittest.TestCase):
    """Test multi-byte message encoding and decoding."""

    def test_empty_message(self):
        encoded = hamming_encode_message(b"")
        self.assertEqual(len(encoded), 0)
        decoded, corrections, _ = hamming_decode_message(encoded)
        self.assertEqual(decoded, b"")
        self.assertEqual(corrections, 0)

    def test_single_byte(self):
        encoded = hamming_encode_message(b"A")
        self.assertEqual(len(encoded), 12)
        decoded, corrections, _ = hamming_decode_message(encoded)
        self.assertEqual(decoded, b"A")
        self.assertEqual(corrections, 0)

    def test_hello_world(self):
        msg = b"Hello, World!"
        encoded = hamming_encode_message(msg)
        self.assertEqual(len(encoded), len(msg) * 12)
        decoded, corrections, _ = hamming_decode_message(encoded)
        self.assertEqual(decoded, msg)
        self.assertEqual(corrections, 0)

    def test_max_distributed_length(self):
        """255 bytes (max distributed message) encodes and decodes correctly."""
        msg = bytes(range(256)) * 1  # 256 bytes
        msg = msg[:255]
        encoded = hamming_encode_message(msg)
        self.assertEqual(len(encoded), 255 * 12)
        decoded, corrections, _ = hamming_decode_message(encoded)
        self.assertEqual(decoded, msg)
        self.assertEqual(corrections, 0)

    def test_non_multiple_of_12_raises(self):
        with self.assertRaises(ValueError):
            hamming_decode_message(BitArray(11))
        with self.assertRaises(ValueError):
            hamming_decode_message(BitArray(13))


class TestHammingMessageWithErrors(unittest.TestCase):
    """Test error correction across multi-byte messages."""

    def test_one_error_per_block(self):
        """Flip 1 bit in every 12-bit block — all should be corrected."""
        msg = b"Test message!"
        encoded = hamming_encode_message(msg)
        corrupted = BitArray(encoded)
        for i in range(len(msg)):
            # Flip a different position in each block
            flip_pos = i * 12 + (i % 12)
            corrupted.invert(flip_pos)
        decoded, corrections, corrected_idx = hamming_decode_message(corrupted)
        self.assertEqual(decoded, msg)
        self.assertEqual(corrections, len(msg))
        self.assertEqual(corrected_idx, list(range(len(msg))))

    def test_error_in_some_blocks_only(self):
        """Flip 1 bit in only some blocks."""
        msg = b"ABCDEF"
        encoded = hamming_encode_message(msg)
        corrupted = BitArray(encoded)
        # Corrupt blocks 0 and 3 only
        corrupted.invert(0 * 12 + 5)
        corrupted.invert(3 * 12 + 9)
        decoded, corrections, corrected_idx = hamming_decode_message(corrupted)
        self.assertEqual(decoded, msg)
        self.assertEqual(corrections, 2)
        self.assertEqual(corrected_idx, [0, 3])

    def test_clean_message_zero_corrections(self):
        msg = b"No errors here"
        encoded = hamming_encode_message(msg)
        decoded, corrections, _ = hamming_decode_message(encoded)
        self.assertEqual(decoded, msg)
        self.assertEqual(corrections, 0)


class TestHammingParityPositions(unittest.TestCase):
    """Verify parity bit placement follows the standard layout."""

    def test_data_at_correct_positions(self):
        """Encode 0b10000000 (only d1=1) and verify only position 3 (0-indexed 2) is set
        among data positions."""
        encoded = hamming_encode_byte(0x80)  # d1=1, rest=0
        # Data positions (0-indexed): 2,4,5,6,8,9,10,11
        # Only position 2 (d1) should be 1
        self.assertEqual(int(encoded[2]), 1)
        for pos in [4, 5, 6, 8, 9, 10, 11]:
            self.assertEqual(int(encoded[pos]), 0, f"data pos {pos}")

    def test_parity_computed_correctly(self):
        """For a known byte, verify parity bits match manual calculation."""
        # 0x41 = 0b01000001 → d1=0,d2=1,d3=0,d4=0,d5=0,d6=0,d7=0,d8=1
        encoded = hamming_encode_byte(0x41)
        b = [int(bit) for bit in encoded]
        # Verify data bits
        self.assertEqual(b[2], 0)   # d1
        self.assertEqual(b[4], 1)   # d2
        self.assertEqual(b[5], 0)   # d3
        self.assertEqual(b[6], 0)   # d4
        self.assertEqual(b[8], 0)   # d5
        self.assertEqual(b[9], 0)   # d6
        self.assertEqual(b[10], 0)  # d7
        self.assertEqual(b[11], 1)  # d8
        # p1 = d1^d2^d4^d5^d7 = 0^1^0^0^0 = 1
        self.assertEqual(b[0], 1)
        # p2 = d1^d3^d4^d6^d7 = 0^0^0^0^0 = 0
        self.assertEqual(b[1], 0)
        # p4 = d2^d3^d4^d8 = 1^0^0^1 = 0
        self.assertEqual(b[3], 0)
        # p8 = d5^d6^d7^d8 = 0^0^0^1 = 1
        self.assertEqual(b[7], 1)


if __name__ == "__main__":
    unittest.main()
