import math

from bitstring import BitArray
from temporal_cloak.const import TemporalCloakConst


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
    def bits_required(message_len: int) -> int:
        """Return the total number of timing-delay slots needed to transmit a
        message of *message_len* ASCII characters.

        Layout: boundary (16) + payload (message_len*8) + checksum (8) + boundary (16)
        """
        boundary_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        return boundary_bits * 2 + message_len * 8 + 8  # 8 = checksum

    @staticmethod
    def min_image_size(message_len: int,
                       chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> int:
        """Return the minimum image file size (bytes) required to carry a
        message of *message_len* characters at the given chunk size.

        Each chunk after the first provides one delay slot, so we need
        (bits_required + 1) chunks total.
        """
        total_bits = TemporalCloakEncoding.bits_required(message_len)
        chunks_needed = total_bits + 1  # +1 for the first chunk (no delay)
        # ceil(size / chunk_size) >= chunks_needed when size >= (chunks_needed-1)*chunk_size + 1
        return (chunks_needed - 1) * chunk_size + 1

    @staticmethod
    def validate_image_size(image_size: int, message_len: int,
                            chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> bool:
        """Return True if an image of *image_size* bytes can carry a message
        of *message_len* characters."""
        available_chunks = math.ceil(image_size / chunk_size)
        available_slots = available_chunks - 1
        return available_slots >= TemporalCloakEncoding.bits_required(message_len)

    @staticmethod
    def max_message_len(image_size: int,
                        chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> int:
        """Return the maximum message length (characters) an image can carry."""
        available_chunks = math.ceil(image_size / chunk_size)
        available_slots = available_chunks - 1
        # available_slots >= boundary*2 + msg_len*8 + 8
        # msg_len <= (available_slots - 40) / 8
        boundary_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        overhead = boundary_bits * 2 + 8  # two boundaries + checksum
        return max(0, (available_slots - overhead) // 8)

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
