"""Integration tests for Hamming(12,8) FEC with the encoding/decoding pipeline."""

import math
import time
import unittest

from bitstring import BitArray, BitStream

from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.encoding import FrontloadedEncoder, DistributedEncoder
from temporal_cloak.decoding import (
    FrontloadedDecoder, DistributedDecoder, AutoDecoder,
)
from temporal_cloak.fec import HammingFec


class TestFrontloadedHammingRoundTrip(unittest.TestCase):
    """Encode with Hamming, decode, verify message."""

    def test_short_message(self):
        enc = FrontloadedEncoder(hamming=True)
        enc.message = "hi"

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC

        for delay in enc.delays:
            decoder.add_bit_by_delay(delay)

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "hi")
        self.assertTrue(decoder.checksum_valid)

    def test_longer_message(self):
        enc = FrontloadedEncoder(hamming=True)
        enc.message = "Hello World!"

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC

        for delay in enc.delays:
            decoder.add_bit_by_delay(delay)

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "Hello World!")
        self.assertTrue(decoder.checksum_valid)

    def test_boundary_is_ff02(self):
        enc = FrontloadedEncoder(hamming=True)
        enc.message = "hi"
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS_FEC)
        pos = enc._message_bits_padded.find(boundary)
        self.assertTrue(len(pos) > 0)


class TestDistributedHammingRoundTrip(unittest.TestCase):
    """Encode with Hamming in distributed mode, decode, verify message."""

    def test_short_message(self):
        enc = DistributedEncoder(hamming=True)
        enc.message = "hi"
        image_size = 50000
        chunk_size = TemporalCloakConst.CHUNK_SIZE_TORNADO
        delays = enc.generate_delays(image_size, key=42)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = DistributedDecoder(total_gaps)
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED_FEC

        decoder._start_time = decoder._last_recv_time = time.monotonic()
        for delay in delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.completed:
                break

        self.assertTrue(decoder.completed)
        self.assertEqual(decoder._last_message, "hi")
        self.assertTrue(decoder.checksum_valid)

    def test_boundary_is_ff03(self):
        enc = DistributedEncoder(hamming=True)
        enc.message = "hi"
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED_FEC)
        # Check the preamble contains the FEC boundary
        preamble_bits = enc._message_bits_padded[:16]
        self.assertEqual(preamble_bits, boundary)


class TestAutoDecoderHammingDetection(unittest.TestCase):
    """AutoDecoder should detect Hamming from boundary marker bits."""

    def test_frontloaded_hamming_detected(self):
        enc = FrontloadedEncoder(hamming=True)
        enc.message = "OK"
        total_gaps = len(enc.delays)

        decoder = AutoDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()
        for delay in enc.delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()

        self.assertEqual(decoder.mode, "frontloaded")
        self.assertTrue(decoder.hamming)
        self.assertEqual(decoder.message, "OK")
        self.assertTrue(decoder.checksum_valid)

    def test_distributed_hamming_detected(self):
        enc = DistributedEncoder(hamming=True)
        enc.message = "OK"
        image_size = 50000
        chunk_size = TemporalCloakConst.CHUNK_SIZE_TORNADO
        delays = enc.generate_delays(image_size, key=42)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = AutoDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()
        for delay in delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.message_complete:
                break

        self.assertEqual(decoder.mode, "distributed")
        self.assertTrue(decoder.hamming)
        self.assertEqual(decoder.message, "OK")
        self.assertTrue(decoder.checksum_valid)

    def test_non_hamming_backward_compat(self):
        """Non-Hamming encoded messages still decode correctly."""
        enc = FrontloadedEncoder(hamming=False)
        enc.message = "OK"
        total_gaps = len(enc.delays)

        decoder = AutoDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()
        for delay in enc.delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()

        self.assertEqual(decoder.mode, "frontloaded")
        self.assertFalse(decoder.hamming)
        self.assertEqual(decoder.message, "OK")
        self.assertTrue(decoder.checksum_valid)

    def test_distributed_non_hamming_backward_compat(self):
        enc = DistributedEncoder(hamming=False)
        enc.message = "OK"
        image_size = 50000
        chunk_size = TemporalCloakConst.CHUNK_SIZE_TORNADO
        delays = enc.generate_delays(image_size, key=42)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = AutoDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()
        for delay in delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.message_complete:
                break

        self.assertEqual(decoder.mode, "distributed")
        self.assertFalse(decoder.hamming)
        self.assertEqual(decoder.message, "OK")
        self.assertTrue(decoder.checksum_valid)


class TestHammingErrorCorrection(unittest.TestCase):
    """Verify Hamming corrects single-bit errors during decode."""

    def test_single_bit_error_corrected(self):
        """Flip 1 bit in a Hamming block — should be auto-corrected."""
        enc = FrontloadedEncoder(hamming=True)
        enc.message = "hi"
        bits = BitArray(enc._message_bits_padded)

        # Flip a bit inside the Hamming payload (after the 16-bit boundary)
        flip_pos = 16 + 5  # inside the first Hamming block
        bits.invert(flip_pos)

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC
        for bit in bits:
            decoder.add_bit(int(bit))

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "hi")
        self.assertTrue(decoder.checksum_valid)
        self.assertGreater(decoder.hamming_corrections, 0)

    def test_one_error_per_block_all_corrected(self):
        """Flip 1 bit in every 12-bit Hamming block — all corrected."""
        enc = FrontloadedEncoder(hamming=True)
        enc.message = "Test"
        bits = BitArray(enc._message_bits_padded)

        # Payload starts after 16-bit boundary
        payload_start = 16
        # Number of Hamming blocks = (msg_len + 1 checksum) = 5 blocks
        num_blocks = len(enc.message) + 1
        for i in range(num_blocks):
            flip_pos = payload_start + i * 12 + (i % 12)
            bits.invert(flip_pos)

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC
        for bit in bits:
            decoder.add_bit(int(bit))

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "Test")
        self.assertTrue(decoder.checksum_valid)
        self.assertEqual(decoder.hamming_corrections, num_blocks)


class TestHammingWithLowConfidenceCorrection(unittest.TestCase):
    """Verify Hamming and low-confidence correction stack correctly."""

    def test_hamming_fixes_before_checksum(self):
        """Hamming should fix single-bit errors so checksum passes,
        avoiding the need for low-confidence bit correction."""
        enc = FrontloadedEncoder(hamming=True)
        enc.message = "AB"
        bits = BitArray(enc._message_bits_padded)

        # Flip 1 bit in one Hamming block
        bits.invert(16 + 3)

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC
        for bit in bits:
            decoder.add_bit(int(bit))

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertTrue(decoder.checksum_valid)
        # No low-confidence correction needed since Hamming handled it
        corrected, flipped = decoder.try_correct_low_confidence_bits()
        self.assertIsNone(corrected)


class TestHammingBitsRequired(unittest.TestCase):
    """Verify capacity calculations with Hamming."""

    def test_frontloaded_bits_more_with_hamming(self):
        msg_len = 10
        without = FrontloadedEncoder.bits_required(msg_len, hamming=False)
        with_h = FrontloadedEncoder.bits_required(msg_len, hamming=True)
        # Hamming: (10+1)*12 + 32 = 164. Without: 10*8 + 8 + 32 = 120
        self.assertGreater(with_h, without)

    def test_distributed_bits_more_with_hamming(self):
        msg_len = 10
        without = DistributedEncoder.bits_required(msg_len, hamming=False)
        with_h = DistributedEncoder.bits_required(msg_len, hamming=True)
        self.assertGreater(with_h, without)

    def test_max_message_len_less_with_hamming(self):
        image_size = 50000
        without = FrontloadedEncoder.max_message_len(image_size, hamming=False)
        with_h = FrontloadedEncoder.max_message_len(image_size, hamming=True)
        self.assertGreater(without, with_h)

    def test_distributed_max_message_len_less_with_hamming(self):
        image_size = 50000
        without = DistributedEncoder.max_message_len(image_size, hamming=False)
        with_h = DistributedEncoder.max_message_len(image_size, hamming=True)
        self.assertGreater(without, with_h)

    def test_validate_image_size_hamming(self):
        msg_len = 5
        min_size = FrontloadedEncoder.min_image_size(msg_len, hamming=True)
        self.assertTrue(FrontloadedEncoder.validate_image_size(
            min_size, msg_len, hamming=True))
        # Slightly smaller image should fail
        self.assertFalse(FrontloadedEncoder.validate_image_size(
            min_size - 256, msg_len, hamming=True))


class TestHammingBoundaryMarkers(unittest.TestCase):
    """Verify correct boundary markers are used."""

    def test_frontloaded_no_hamming_uses_ff00(self):
        enc = FrontloadedEncoder(hamming=False)
        self.assertEqual(enc.BOUNDARY, TemporalCloakConst.BOUNDARY_BITS)

    def test_frontloaded_hamming_uses_ff02(self):
        enc = FrontloadedEncoder(hamming=True)
        self.assertEqual(enc.BOUNDARY, TemporalCloakConst.BOUNDARY_BITS_FEC)

    def test_distributed_no_hamming_uses_ff01(self):
        enc = DistributedEncoder(hamming=False)
        self.assertEqual(enc.BOUNDARY, TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED)

    def test_distributed_hamming_uses_ff03(self):
        enc = DistributedEncoder(hamming=True)
        self.assertEqual(enc.BOUNDARY, TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED_FEC)


class TestHammingAutoDecoderProperties(unittest.TestCase):
    """Verify AutoDecoder exposes Hamming properties."""

    def test_hamming_property_before_bootstrap(self):
        decoder = AutoDecoder(100)
        self.assertIsNone(decoder.hamming)

    def test_hamming_corrections_before_bootstrap(self):
        decoder = AutoDecoder(100)
        self.assertEqual(decoder.hamming_corrections, 0)

    def test_hamming_corrections_after_decode(self):
        enc = FrontloadedEncoder(hamming=True)
        enc.message = "OK"
        bits = BitArray(enc._message_bits_padded)
        # Flip a bit to trigger a Hamming correction
        bits.invert(16 + 7)

        total_gaps = len(enc.delays)
        decoder = AutoDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()
        for delay in enc.delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()

        # Note: AutoDecoder feeds delays, not raw bits, so the flip above
        # doesn't apply. Instead test via direct FrontloadedDecoder.
        dec = FrontloadedDecoder()
        dec._hamming = True
        dec._fec = HammingFec()
        dec.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC
        for bit in bits:
            dec.add_bit(int(bit))
        result, completed, _ = dec.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "OK")
        self.assertGreater(dec.hamming_corrections, 0)


class TestFuzzyStartBoundaryFallback(unittest.TestCase):
    """Fuzzy start boundary can produce false positives that break FEC alignment.

    When noise before the real boundary fuzzy-matches within max_errors,
    the payload between that false start and the real end boundary has
    extra bits, breaking Hamming block alignment.  The decoder should
    fall back to the exact start boundary in that case.
    """

    def _encode_bits(self, message, hamming=True):
        """Helper: encode a message and return the raw bit array."""
        enc = FrontloadedEncoder(hamming=hamming)
        enc.message = message
        return BitArray(enc._message_bits_padded)

    def test_noise_before_boundary_falls_back_to_exact(self):
        """Prepend bits that fuzzy-match the FEC boundary; exact match should win."""
        bits = self._encode_bits("hi")
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS_FEC)

        # Build a near-boundary pattern (2 bit errors from 0xFF02) placed
        # 3 bits before the real start, so fuzzy match finds it first.
        fake = BitArray(boundary)
        fake.invert(0)
        fake.invert(1)  # 2 errors — within max_errors=2
        # Prepend: 3 noise bits + fake boundary fragment (only first 13 bits,
        # so that bit 0 of the real boundary starts at offset 3+13=16 which
        # overlaps with the fake).  Simpler: just prepend 3 bits + full fake.
        padded = BitArray(bin='010') + fake[:13] + bits

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC
        for bit in padded:
            decoder.add_bit(int(bit))

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed, "Message should complete via exact-match fallback")
        self.assertEqual(result, "hi")
        self.assertTrue(decoder.checksum_valid)

    def test_exact_fallback_produces_aligned_payload(self):
        """When fuzzy start is off by N bits, the exact start gives block-aligned payload."""
        bits = self._encode_bits("Test")
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS_FEC)

        # Prepend 5 bits of noise that happen to fuzzy-match the boundary
        fake = BitArray(boundary)
        fake.invert(4)
        fake.invert(7)
        padded = BitArray(bin='10110') + fake[:11] + bits

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC
        for bit in padded:
            decoder.add_bit(int(bit))

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "Test")
        self.assertTrue(decoder.checksum_valid)

    def test_corrupted_start_boundary_still_uses_fuzzy(self):
        """A real corrupted start boundary should still be recovered by fuzzy match."""
        bits = self._encode_bits("ok")
        # Corrupt 1 bit in the start boundary (first 16 bits)
        bits.invert(3)

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC
        for bit in bits:
            decoder.add_bit(int(bit))

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed, "Fuzzy match should recover corrupted start boundary")
        self.assertEqual(result, "ok")
        self.assertTrue(decoder.checksum_valid)

    def test_no_warning_on_partial_fec_decode(self):
        """Partial FEC payload during streaming should not warn about misalignment."""
        import warnings
        bits = self._encode_bits("hi")

        decoder = FrontloadedDecoder()
        decoder._hamming = True
        decoder._fec = HammingFec()
        decoder.BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_FEC

        # Feed only enough bits for start boundary + a few payload bits (not complete)
        partial_len = 16 + 10  # boundary + partial hamming block
        for bit in bits[:partial_len]:
            decoder.add_bit(int(bit))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result, completed, _ = decoder.bits_to_message()
            fec_warnings = [x for x in w if "not aligned" in str(x.message)]
            self.assertEqual(len(fec_warnings), 0,
                             "Partial decode should not warn about FEC alignment")
        self.assertFalse(completed)


if __name__ == "__main__":
    unittest.main()
