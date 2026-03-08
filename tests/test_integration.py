import unittest
from bitstring import BitArray
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.encoding import FrontloadedEncoder, DistributedEncoder
from temporal_cloak.decoding import FrontloadedDecoder, DistributedDecoder, AutoDecoder


class TestFrontloadedRoundTrip(unittest.TestCase):
    """Encode a message to delays, feed delays into decoder, verify output."""

    def test_round_trip(self):
        message = "hi"
        encoder = FrontloadedEncoder()
        encoder.message = message

        decoder = FrontloadedDecoder()
        for delay in encoder.delays:
            decoder.add_bit_by_delay(delay)

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, message)
        self.assertTrue(decoder.checksum_valid)

    def test_round_trip_longer_message(self):
        message = "TemporalCloak works!"
        encoder = FrontloadedEncoder()
        encoder.message = message

        decoder = FrontloadedDecoder()
        for delay in encoder.delays:
            decoder.add_bit_by_delay(delay)

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, message)
        self.assertTrue(decoder.checksum_valid)


class TestDistributedRoundTrip(unittest.TestCase):
    """Encode with distributed delays, feed through decoder, verify message."""

    def _round_trip(self, message, image_size=50000):
        import math
        import time
        chunk_size = 256
        encoder = DistributedEncoder()
        encoder.message = message
        delays = encoder.generate_delays(image_size, chunk_size)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = DistributedDecoder(total_gaps)
        # Simulate mark_time by setting up timing state and injecting delays
        decoder._start_time = decoder._last_recv_time = time.monotonic()

        for delay in delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.completed:
                break

        return decoder._last_message, decoder.completed, decoder

    def test_distributed_round_trip(self):
        msg, completed, decoder = self._round_trip("hi")
        self.assertTrue(completed)
        self.assertEqual(msg, "hi")
        self.assertTrue(decoder.checksum_valid)

    def test_distributed_round_trip_longer(self):
        msg, completed, decoder = self._round_trip("TemporalCloak works!", image_size=100000)
        self.assertTrue(completed)
        self.assertEqual(msg, "TemporalCloak works!")
        self.assertTrue(decoder.checksum_valid)

    def test_frontloaded_still_works(self):
        """Existing frontloaded round-trip should be unaffected."""
        message = "hello"
        encoder = FrontloadedEncoder()
        encoder.message = message
        decoder = FrontloadedDecoder()
        for delay in encoder.delays:
            decoder.add_bit_by_delay(delay)
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, message)
        self.assertTrue(decoder.checksum_valid)


class TestBoundaryMarkers(unittest.TestCase):
    """Verify each encoder uses the correct boundary marker."""

    def test_frontloaded_uses_ff00(self):
        enc = FrontloadedEncoder()
        enc.message = "hi"
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        pos = enc._message_bits_padded.find(boundary)
        self.assertTrue(len(pos) > 0)

    def test_distributed_uses_ff01(self):
        enc = DistributedEncoder()
        enc.message = "hi"
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED)
        pos = enc._message_bits_padded.find(boundary)
        self.assertTrue(len(pos) > 0)

    def test_distributed_does_not_contain_ff00(self):
        enc = DistributedEncoder()
        enc.message = "hi"
        boundary_ff00 = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        pos = enc._message_bits_padded.find(boundary_ff00)
        self.assertEqual(len(pos), 0)


class TestAutoDecoderFrontloaded(unittest.TestCase):
    """AutoDecoder correctly dispatches frontloaded streams."""

    def test_auto_round_trip_frontloaded(self):
        import time

        encoder = FrontloadedEncoder()
        encoder.message = "hi"

        decoder = AutoDecoder(total_gaps=0)
        decoder._start_time = decoder._last_recv_time = time.monotonic()

        for delay in encoder.delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.completed:
                break

        self.assertEqual(decoder.mode, "frontloaded")
        self.assertTrue(decoder.completed)
        self.assertEqual(decoder._last_message, "hi")
        self.assertTrue(decoder.checksum_valid)

    def test_auto_round_trip_frontloaded_longer(self):
        import time

        encoder = FrontloadedEncoder()
        encoder.message = "TemporalCloak!"

        decoder = AutoDecoder(total_gaps=0)
        decoder._start_time = decoder._last_recv_time = time.monotonic()

        for delay in encoder.delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.completed:
                break

        self.assertEqual(decoder.mode, "frontloaded")
        self.assertTrue(decoder.completed)
        self.assertEqual(decoder._last_message, "TemporalCloak!")
        self.assertTrue(decoder.checksum_valid)


class TestAutoDecoderDistributed(unittest.TestCase):
    """AutoDecoder correctly dispatches distributed streams."""

    def test_auto_round_trip_distributed(self):
        import math
        import time

        encoder = DistributedEncoder()
        encoder.message = "hi"
        image_size = 50000
        chunk_size = 256
        delays = encoder.generate_delays(image_size, chunk_size)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = AutoDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()

        for delay in delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.completed:
                break

        self.assertEqual(decoder.mode, "distributed")
        self.assertTrue(decoder.completed)
        self.assertEqual(decoder._last_message, "hi")
        self.assertTrue(decoder.checksum_valid)

    def test_auto_round_trip_distributed_longer(self):
        import math
        import time

        encoder = DistributedEncoder()
        encoder.message = "TemporalCloak!"
        image_size = 100000
        chunk_size = 256
        delays = encoder.generate_delays(image_size, chunk_size)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = AutoDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()

        for delay in delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.completed:
                break

        self.assertEqual(decoder.mode, "distributed")
        self.assertTrue(decoder.completed)
        self.assertEqual(decoder._last_message, "TemporalCloak!")
        self.assertTrue(decoder.checksum_valid)


class TestAutoDecoderEdgeCases(unittest.TestCase):
    """AutoDecoder edge cases: pre-bootstrap state, fewer than 16 delays."""

    def test_fewer_than_16_delays(self):
        """Feed only 10 delays — mode/delegate should be None, completed False."""
        import time
        decoder = AutoDecoder(total_gaps=200)
        decoder._start_time = decoder._last_recv_time = time.monotonic()
        for _ in range(10):
            decoder._last_recv_time -= TemporalCloakConst.BIT_1_TIME_DELAY
            decoder.mark_time()
        self.assertIsNone(decoder.mode)
        self.assertIsNone(decoder.delegate)
        self.assertFalse(decoder.completed)

    def test_properties_before_bootstrap(self):
        """All proxy properties return safe defaults before any delays."""
        decoder = AutoDecoder(total_gaps=100)
        self.assertIsNone(decoder.mode)
        self.assertIsNone(decoder.delegate)
        self.assertFalse(decoder.completed)
        self.assertIsNone(decoder.checksum_valid)
        self.assertEqual(decoder.threshold, TemporalCloakConst.MIDPOINT_TIME)
        self.assertEqual(decoder.confidence_scores, [])
        self.assertIsNone(decoder._last_message)
        self.assertEqual(decoder.bit_count, 0)
        self.assertEqual(decoder.partial_message, "")
        self.assertEqual(decoder.message, "")
        self.assertFalse(decoder.message_complete)
        # bits_to_message returns empty tuple before bootstrap
        result, completed, end_pos = decoder.bits_to_message()
        self.assertEqual(result, "")
        self.assertFalse(completed)
        self.assertIsNone(end_pos)

    def test_bits_returns_empty_before_bootstrap(self):
        """bits property returns empty BitStream before any delays."""
        from bitstring import BitStream
        decoder = AutoDecoder(total_gaps=100)
        self.assertEqual(len(decoder.bits), 0)


class TestAutoDecoderProgressProperties(unittest.TestCase):
    """Test bit_count, partial_message, message, and message_complete during decode."""

    def test_frontloaded_properties_during_decode(self):
        """Feed delays incrementally, verify properties at each stage."""
        import time

        encoder = FrontloadedEncoder()
        encoder.message = "hello"
        delays = encoder.delays
        boundary_len = 16  # 0xFF00

        decoder = AutoDecoder(total_gaps=0)
        decoder._start_time = decoder._last_recv_time = time.monotonic()

        # Stage 1: Before any delays
        self.assertEqual(decoder.bit_count, 0)
        self.assertEqual(decoder.partial_message, "")
        self.assertEqual(decoder.message, "")
        self.assertFalse(decoder.message_complete)

        # Stage 2: Feed the boundary (first 16 delays) — triggers bootstrap
        for delay in delays[:boundary_len]:
            decoder._last_recv_time -= delay
            decoder.mark_time()

        self.assertEqual(decoder.bit_count, boundary_len)
        self.assertEqual(decoder.mode, "frontloaded")
        # Still in preamble, no message chars yet
        self.assertEqual(decoder.partial_message, "")
        self.assertFalse(decoder.message_complete)

        # Stage 3: Feed enough delays for ~2 complete characters (16 more bits)
        # After preamble, each 8 bits = 1 char. partial_message shows
        # complete_chars - 1 to avoid half-decoded trailing chars.
        two_chars_worth = delays[boundary_len:boundary_len + 16]
        for delay in two_chars_worth:
            decoder._last_recv_time -= delay
            decoder.mark_time()

        self.assertEqual(decoder.bit_count, boundary_len + 16)
        # 16 data bits = 2 complete chars, display 2-1 = 1 char
        self.assertEqual(len(decoder.partial_message), 1)
        self.assertEqual(decoder.partial_message, "h")
        self.assertFalse(decoder.message_complete)

        # Stage 4: Feed all remaining delays to complete the message
        for delay in delays[boundary_len + 16:]:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.message_complete:
                break

        self.assertTrue(decoder.message_complete)
        self.assertEqual(decoder.message, "hello")
        self.assertTrue(decoder.checksum_valid)

    def test_distributed_properties_during_decode(self):
        """bit_count and message work correctly in distributed mode."""
        import math
        import time

        encoder = DistributedEncoder()
        encoder.message = "hi"
        image_size = 50000
        chunk_size = 256
        delays = encoder.generate_delays(image_size, chunk_size)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = AutoDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()

        for delay in delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.message_complete:
                break

        self.assertEqual(decoder.mode, "distributed")
        self.assertTrue(decoder.message_complete)
        self.assertEqual(decoder.message, "hi")
        self.assertGreater(decoder.bit_count, 0)

    def test_bit_count_increments(self):
        """bit_count should grow monotonically as delays are fed."""
        import time

        encoder = FrontloadedEncoder()
        encoder.message = "AB"

        decoder = AutoDecoder(total_gaps=0)
        decoder._start_time = decoder._last_recv_time = time.monotonic()

        prev_count = 0
        for delay in encoder.delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            self.assertGreaterEqual(decoder.bit_count, prev_count)
            prev_count = decoder.bit_count

        self.assertTrue(decoder.message_complete)
        self.assertEqual(decoder.message, "AB")


class TestDistributedEdgeCases(unittest.TestCase):
    """Distributed mode edge cases: max length, minimum image, empty message."""

    def _round_trip(self, message, image_size=50000):
        import math
        import time
        chunk_size = 256
        encoder = DistributedEncoder()
        encoder.message = message
        delays = encoder.generate_delays(image_size, chunk_size)
        total_gaps = math.ceil(image_size / chunk_size) - 1

        decoder = DistributedDecoder(total_gaps)
        decoder._start_time = decoder._last_recv_time = time.monotonic()
        for delay in delays:
            decoder._last_recv_time -= delay
            decoder.mark_time()
            if decoder.completed:
                break
        return decoder._last_message, decoder.completed, decoder

    def test_max_length_255_round_trip(self):
        """Full round-trip with 255-char message (max distributed length)."""
        msg = "A" * 255
        result, completed, decoder = self._round_trip(msg, image_size=1_000_000)
        self.assertTrue(completed)
        self.assertEqual(result, msg)
        self.assertTrue(decoder.checksum_valid)

    def test_min_image_size_round_trip(self):
        """Round-trip with the minimum viable image size for a message."""
        msg = "hi"
        min_size = DistributedEncoder.min_image_size(len(msg))
        result, completed, decoder = self._round_trip(msg, image_size=min_size)
        self.assertTrue(completed)
        self.assertEqual(result, msg)
        self.assertTrue(decoder.checksum_valid)

    def test_empty_message_distributed_round_trip(self):
        """Empty message round-trip in distributed mode completes without crashing.

        Note: empty payload means only the 8-bit checksum (0x00) sits between
        boundaries. decode() doesn't strip it (len <= 8), so result is '\\x00'.
        """
        result, completed, decoder = self._round_trip("")
        self.assertTrue(completed)
        # Checksum byte not stripped for empty payload — known edge case
        self.assertIn(result, ("", "\x00"))

    def test_empty_message_frontloaded_round_trip(self):
        """Empty message round-trip in frontloaded mode completes without crashing."""
        encoder = FrontloadedEncoder()
        encoder.message = ""
        decoder = FrontloadedDecoder()
        for delay in encoder.delays:
            decoder.add_bit_by_delay(delay)
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertIn(result, ("", "\x00"))

    def test_special_ascii_round_trip(self):
        """Round-trip with \\x01, \\x7f, and \\x00 characters."""
        msg = "\x01\x7f\x00"
        encoder = FrontloadedEncoder()
        encoder.message = msg
        decoder = FrontloadedDecoder()
        for delay in encoder.delays:
            decoder.add_bit_by_delay(delay)
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, msg)
        self.assertTrue(decoder.checksum_valid)


class TestCrossBoundary(unittest.TestCase):
    """Cross-mode boundary safety: wrong decoder should not produce valid decode."""

    def test_frontloaded_into_distributed_decoder(self):
        """Frontloaded message fed to DistributedDecoder should not produce a valid decode."""
        import math
        encoder = FrontloadedEncoder()
        encoder.message = "secret"

        # Use a DistributedDecoder with some total_gaps
        total_gaps = 500
        decoder = DistributedDecoder(total_gaps)

        # Feed frontloaded delays (only covers the first N gaps)
        for delay in encoder.delays:
            decoder.add_bit_by_delay(delay)
            decoder._gap_index += 1
            if decoder._gap_index == TemporalCloakConst.PREAMBLE_BITS and not decoder._preamble_collected:
                decoder._process_preamble()

        result, completed, _ = decoder.bits_to_message()
        # Should NOT correctly decode the frontloaded message
        if completed:
            self.assertNotEqual(result, "secret")


if __name__ == '__main__':
    unittest.main()
