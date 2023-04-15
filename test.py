import unittest
from BitCloakConst import BitCloakConst
from BitCloakDecoding import BitCloakDecoding
from bitstring import Bits, BitArray, BitStream


class TestBitCloakDecoding(unittest.TestCase):

    def setUp(self):
        self.decoding = BitCloakDecoding()
        # "hello" with the boundary bits in front and back, plus random bytes after
        self.test_bits = BitStream('0x0xff0068656c6c6fff006865')
        self.test_message = 'hello'

    def test_add_bit(self):
        self.decoding.add_bit(1)
        self.assertEqual(self.decoding.bits, BitStream('0b1'))

    def test_add_bit_by_delay(self):
        self.decoding.add_bit_by_delay(BitCloakConst.BIT_1_LOWER_BOUND)
        self.assertEqual(self.decoding.bits, BitStream('0b1'))
        self.decoding.add_bit_by_delay(BitCloakConst.BIT_0_LOWER_BOUND)
        self.assertEqual(self.decoding.bits, BitStream('0b10'))

    def test_find_boundary(self):
        result = self.decoding.find_boundary(self.test_bits)
        self.assertEqual(result, 0)

    def test_bits_to_message(self):
        self.decoding._bits = self.test_bits
        result, completed, end_pos = self.decoding.bits_to_message()
        self.assertEqual(result, self.test_message)
        self.assertTrue(completed)

    def test_jump_to_next_message(self):
        self.decoding._bits = self.test_bits
        self.decoding.bits_to_message()
        self.decoding.jump_to_next_message()
        self.assertEqual(self.decoding.bits, BitStream('0xFF006865'))


class TestFindBoundary(unittest.TestCase):
    def setUp(self):
        self.my_obj = BitCloakDecoding()
        self.bits_with_boundary = BitArray('0b0101010101') + BitArray(BitCloakConst.BOUNDARY_BITS) + BitArray('0b0101010101')
        self.bits_with_two_boundaries = BitArray('0b0101010101') + BitArray(BitCloakConst.BOUNDARY_BITS) + BitArray('0b0101010101') + BitArray(BitCloakConst.BOUNDARY_BITS)
        self.bits_without_boundary = BitArray('0b0101010101010101010101010101')

    def test_boundary_found(self):
        result = self.my_obj.find_boundary(self.bits_with_boundary)
        self.assertEqual(result, 10)

    def test_boundary_not_found(self):
        result = self.my_obj.find_boundary(self.bits_without_boundary)
        self.assertIsNone(result)

    def test_two_boundaries(self):
        first = self.my_obj.find_boundary(self.bits_with_two_boundaries)+1
        second = self.my_obj.find_boundary(self.bits_with_two_boundaries, first)
        # 10 + 16 + 10 + 16 = 52
        self.assertEqual(second, 36)


if __name__ == '__main__':
    unittest.main()
