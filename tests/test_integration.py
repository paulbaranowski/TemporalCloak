import unittest
from temporal_cloak.encoding import TemporalCloakEncoding
from temporal_cloak.decoding import TemporalCloakDecoding


class TestEncodeDecodeRoundTrip(unittest.TestCase):
    """Encode a message to delays, feed delays into decoder, verify output."""

    def test_round_trip(self):
        message = "hi"
        encoder = TemporalCloakEncoding()
        encoder.message = message

        decoder = TemporalCloakDecoding()
        for delay in encoder.delays:
            decoder.add_bit_by_delay(delay)

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, message)
        self.assertTrue(decoder.checksum_valid)

    def test_round_trip_longer_message(self):
        message = "TemporalCloak works!"
        encoder = TemporalCloakEncoding()
        encoder.message = message

        decoder = TemporalCloakDecoding()
        for delay in encoder.delays:
            decoder.add_bit_by_delay(delay)

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, message)
        self.assertTrue(decoder.checksum_valid)


if __name__ == '__main__':
    unittest.main()
