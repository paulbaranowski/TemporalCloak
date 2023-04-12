import unittest
from client import string_to_bits, generate_delays
from server import bits_to_string
from common import *


class TestStringToBits(unittest.TestCase):
    def test_single_character(self):
        bits = string_to_bits('a')
        self.assertEqual(bits, [0, 1, 1, 0, 0, 0, 0, 1])

    def test_multiple_characters(self):
        bits = string_to_bits('hello')
        self.assertEqual(bits, [0, 1, 1, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1])


class TestBitsToString(unittest.TestCase):
    def test_single_character(self):
        bits = [0, 1, 1, 0, 0, 0, 0, 1]
        self.assertEqual(bits_to_string(bits), 'a')

    def test_single_character_with_boundary(self):
        padding = [0] * 8 + [1] * 8
        bits = padding+ [0, 1, 1, 0, 0, 0, 0, 1]
        self.assertEqual(bits_to_string(bits, True), 'a')

    def test_single_character_with_boundary_and_garbage(self):
        padding = [0] * 8 + [1] * 8
        bits = [0, 1, 1, 0, 0, 0, 0, 1] + padding + [0, 1, 1, 0, 0, 0, 0, 1]
        self.assertEqual(bits_to_string(bits, True), 'a')

    def test_multiple_characters(self):
        bits = [0, 1, 1, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1]
        self.assertEqual(bits_to_string(bits), 'hello')

    def test_multiple_characters_with_boundary(self):
        padding = [0] * 8 + [1] * 8
        bits = padding + [0, 1, 1, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1]
        self.assertEqual(bits_to_string(bits, True), 'hello')

    def test_empty_list(self):
        bits = []
        self.assertEqual(bits_to_string(bits), '')

    def test_incomplete_byte(self):
        bits = [0, 1, 1, 0, 0, 0, 0]
        self.assertRaises(ValueError, bits_to_string, bits)


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
