from bitstring import BitArray
import random
from TemporalCloakConst import TemporalCloakConst


class TemporalCloakEncoding:
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
    def byte_len(self):
        return len(self._message_encoded)

    @property
    def delays(self):
        return self._delays

    @property
    def bits(self):
        return self._message_bits

    @staticmethod
    def encode_message(msg: str):
        try:
            return True, msg.encode('ascii')
        except UnicodeEncodeError:
            print(f"Failed to encode message '{msg}'")
            return False, ''


    @message.setter
    def message(self, value: str) -> None:
        self._message = value
        _, self._message_encoded = TemporalCloakEncoding.encode_message(self._message)
        self._message_bits = BitArray(self._message_encoded)
        print("Message bits: {}".format(self._message_bits))
        self._message_bits_padded = BitArray(self._message_bits)
        self._message_bits_padded.prepend(TemporalCloakConst.BOUNDARY_BITS)
        print("Message bits with boundary: {}".format(self._message_bits_padded))
        self.generate_delays()

    def generate_delays(self) -> list:
        for bit in self._message_bits_padded:
            if bit:
                delay = TemporalCloakConst.BIT_1_TIME_DELAY
            else:
                delay = TemporalCloakConst.BIT_0_TIME_DELAY
            self._delays.append(delay)
        # print(self._delays)
        return self._delays

    def __str__(self):
        result = "Message: '{}'\n".format(self.message)
        result += "Num bytes: {}\n".format(self.byte_len)
        result += "Message bits: {}\n".format(self._message_bits)
        return result

    def __repr__(self):
        return f"TemporalCloakEncoding(message='{self.message}')"
