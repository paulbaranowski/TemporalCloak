import unittest
from client import string_to_bits, generate_delays
from server import bits_to_string
from common import *


class TestGenerateDelays(unittest.TestCase):
    def test_all_zeros(self):
        bits = [0, 0, 0, 0, 0, 0, 0, 0, 0]
        delays = generate_delays(bits)
        self.assertEqual(len(delays), 9)
        for delay in delays:
            self.assertGreaterEqual(delay, BIT_0_LOWER_BOUND)
            self.assertLessEqual(delay, BIT_0_UPPER_BOUND)

    def test_all_ones(self):
        bits = [1, 1, 1, 1, 1, 1, 1, 1, 1]
        delays = generate_delays(bits)
        self.assertEqual(len(delays), 9)
        for delay in delays:
            self.assertGreaterEqual(delay, BIT_1_LOWER_BOUND)
            self.assertLessEqual(delay, BIT_1_UPPER_BOUND)

    def test_random_bits(self):
        bits = [0, 1, 0, 1, 1, 0, 1, 0, 0]
        delays = generate_delays(bits)
        self.assertEqual(len(delays), 9)
        for bit, delay in zip(bits, delays):
            if bit == 1:
                self.assertGreaterEqual(delay, BIT_1_LOWER_BOUND)
                self.assertLessEqual(delay, BIT_1_UPPER_BOUND)
            else:
                self.assertGreaterEqual(delay, BIT_0_LOWER_BOUND)
                self.assertLessEqual(delay, BIT_0_UPPER_BOUND)


if __name__ == '__main__':
    unittest.main()
