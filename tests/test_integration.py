import unittest
from temporal_cloak.encoding import FrontloadedEncoder, DistributedEncoder
from temporal_cloak.decoding import FrontloadedDecoder, DistributedDecoder


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


if __name__ == '__main__':
    unittest.main()
