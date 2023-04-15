from bitstring import BitArray
import random
from BitCloakConst import BitCloakConst


class BitCloakEncoding:
    def __init__(self):
        self._message = None
        self._message_encoded = None
        self._message_bits = None
        self._message_bits_padded = None
        self._delays = []

    @property
    def message(self):
        return self._message

    @property
    def delays(self):
        return self._delays

    @property
    def bits(self):
        return self._message_bits

    @message.setter
    def message(self, value: str) -> None:
        self._message = value
        self._message_encoded = self._message.encode('ascii')
        self._message_bits = BitArray(self._message_encoded)
        print("Message bits: {}".format(self._message_bits))
        self._message_bits_padded = BitArray(self._message_bits)
        self._message_bits_padded.prepend(BitCloakConst.BOUNDARY_BITS)
        print("Message bits with boundary: {}".format(self._message_bits_padded))
        self.generate_delays()

    def generate_delays_random(self) -> list:
        for bit in self._message_bits_padded:
            if bit == 1:
                delay = random.uniform(BitCloakConst.BIT_1_LOWER_BOUND, BitCloakConst.BIT_1_UPPER_BOUND)
            else:
                delay = random.uniform(BitCloakConst.BIT_0_LOWER_BOUND, BitCloakConst.BIT_0_UPPER_BOUND)
            self._delays.append(delay)
        return self._delays

    def generate_delays(self) -> list:
        for bit in self._message_bits_padded:
            if bit:
                delay = BitCloakConst.BIT_1_LOWER_BOUND
            else:
                delay = BitCloakConst.BIT_0_LOWER_BOUND
            self._delays.append(delay)
        # print(self._delays)
        return self._delays
