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
    def compute_checksum(data: bytes) -> int:
        """Compute an 8-bit XOR checksum over the given bytes."""
        checksum = 0
        for byte in data:
            checksum ^= byte
        return checksum

    @staticmethod
    def encode_message(msg: str):
        try:
            encoded = msg.encode('ascii')
            # All ASCII bytes are < 0x80, so 0xFF00 boundary can never appear in payload
            assert all(b < 0x80 for b in encoded), \
                f"Message contains non-ASCII byte (>= 0x80); boundary collision possible"
            return True, encoded
        except UnicodeEncodeError:
            print(f"Failed to encode message '{msg}'")
            return False, b''


    @message.setter
    def message(self, value: str) -> None:
        self._message = value
        self._delays = []
        _, self._message_encoded = TemporalCloakEncoding.encode_message(self._message)
        self._message_bits = BitArray(self._message_encoded)
        print("Message bits: {}".format(self._message_bits))
        # Compute XOR checksum and append as 8 bits after message
        checksum = TemporalCloakEncoding.compute_checksum(self._message_encoded)
        checksum_bits = BitArray(uint=checksum, length=8)
        self._message_bits_padded = BitArray(self._message_bits)
        self._message_bits_padded.append(checksum_bits)
        self._message_bits_padded.prepend(TemporalCloakConst.BOUNDARY_BITS)
        self._message_bits_padded.append(TemporalCloakConst.BOUNDARY_BITS)
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
