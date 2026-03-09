import math
import random

from bitstring import BitArray
from temporal_cloak.const import TemporalCloakConst


class TemporalCloakEncoding:
    """Base encoder with shared message preparation and utility methods.

    Subclasses implement _build_delays() to produce mode-specific delay lists.
    """

    BOUNDARY = TemporalCloakConst.BOUNDARY_BITS

    def __init__(self):
        self._message = None
        self._message_encoded = None
        self._message_bits = None
        self._message_bits_padded = None
        self._checksum = None
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
        self._checksum = TemporalCloakEncoding.compute_checksum(self._message_encoded)
        checksum_bits = BitArray(uint=self._checksum, length=8)
        self._message_bits_padded = BitArray(self._message_bits)
        self._message_bits_padded.append(checksum_bits)
        self._message_bits_padded.prepend(self.BOUNDARY)
        self._message_bits_padded.append(self.BOUNDARY)
        print("Message bits with boundary: {}".format(self._message_bits_padded))
        self._build_delays()

    @property
    def checksum(self):
        return self._checksum

    def _build_delays(self) -> None:
        """Override in subclasses to generate mode-specific delays."""
        pass

    def debug_sections(self) -> list[dict]:
        """Return an annotated list of signal-bit sections.

        Each section is a dict with at minimum: label, bits, offset, length.
        Subclasses override to insert mode-specific sections (e.g. key, length).
        """
        boundary = BitArray(self.BOUNDARY)
        boundary_len = len(boundary)
        checksum_bits = BitArray(uint=self._checksum, length=8)

        sections = []
        offset = 0

        sections.append({
            "label": "start_boundary",
            "bits": boundary.bin,
            "hex": boundary.hex,
            "offset": offset,
            "length": boundary_len,
        })
        offset += boundary_len

        # Hook for subclass-specific preamble sections
        extra, offset = self._debug_preamble_sections(offset)
        sections.extend(extra)

        sections.append({
            "label": "message",
            "bits": self._message_bits.bin,
            "text": self._message,
            "offset": offset,
            "length": len(self._message_bits),
        })
        offset += len(self._message_bits)

        sections.append({
            "label": "checksum",
            "bits": checksum_bits.bin,
            "hex": checksum_bits.hex,
            "value": self._checksum,
            "offset": offset,
            "length": 8,
        })
        offset += 8

        sections.append({
            "label": "end_boundary",
            "bits": boundary.bin,
            "hex": boundary.hex,
            "offset": offset,
            "length": boundary_len,
        })

        return sections

    def debug_signal_bits(self) -> BitArray:
        """Return the concatenated signal bits (no filler).

        Subclasses override to include mode-specific preamble bits.
        """
        boundary = BitArray(self.BOUNDARY)
        checksum_bits = BitArray(uint=self._checksum, length=8)
        result = BitArray()
        result.append(boundary)
        result.append(self._debug_preamble_bits())
        result.append(self._message_bits)
        result.append(checksum_bits)
        result.append(boundary)
        return result

    def _debug_preamble_sections(self, offset: int) -> tuple[list[dict], int]:
        """Return extra preamble sections and updated offset. Override in subclasses."""
        return [], offset

    def _debug_preamble_bits(self) -> BitArray:
        """Return extra preamble bits for signal concatenation. Override in subclasses."""
        return BitArray()

    def __str__(self):
        result = "Message: '{}'\n".format(self.message)
        result += "Num bytes: {}\n".format(self.byte_len)
        result += "Message bits: {}\n".format(self._message_bits)
        return result

    def __repr__(self):
        return f"TemporalCloakEncoding(message='{self.message}')"


class FrontloadedEncoder(TemporalCloakEncoding):
    """Encodes messages with all bits front-loaded into the first N chunks.

    After setting the message, self.delays contains one delay per bit,
    delivered contiguously from the start of the transmission.
    """

    def _build_delays(self) -> None:
        for bit in self._message_bits_padded:
            if bit:
                delay = TemporalCloakConst.BIT_1_TIME_DELAY
            else:
                delay = TemporalCloakConst.BIT_0_TIME_DELAY
            self._delays.append(delay)

    @staticmethod
    def bits_required(message_len: int) -> int:
        """Total timing-delay slots: boundary(16) + payload + checksum(8) + boundary(16)."""
        boundary_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        return boundary_bits * 2 + message_len * 8 + 8

    @staticmethod
    def min_image_size(message_len: int,
                       chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> int:
        """Minimum image file size (bytes) to carry *message_len* characters."""
        total_bits = FrontloadedEncoder.bits_required(message_len)
        chunks_needed = total_bits + 1
        return (chunks_needed - 1) * chunk_size + 1

    @staticmethod
    def validate_image_size(image_size: int, message_len: int,
                            chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> bool:
        """Return True if image can carry the message."""
        available_chunks = math.ceil(image_size / chunk_size)
        available_slots = available_chunks - 1
        return available_slots >= FrontloadedEncoder.bits_required(message_len)

    @staticmethod
    def max_message_len(image_size: int,
                        chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> int:
        """Maximum message length (characters) this image can carry."""
        available_chunks = math.ceil(image_size / chunk_size)
        available_slots = available_chunks - 1
        boundary_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        overhead = boundary_bits * 2 + 8
        return max(0, (available_slots - overhead) // 8)

    def __repr__(self):
        return f"FrontloadedEncoder(message='{self.message}')"


class DistributedEncoder(TemporalCloakEncoding):
    """Encodes messages with bits scattered across all chunks via a PRNG key.

    After setting the message, call generate_delays(image_size) to produce
    the full delay list. The delay list is also stored in self.delays.
    """

    BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED

    @staticmethod
    def compute_bit_positions(key: int, total_gaps: int, num_remaining_bits: int) -> list:
        """Deterministically select which gap positions carry message bits.

        Uses the key to seed a PRNG, shuffles the available positions
        (after the contiguous preamble), and returns the first
        *num_remaining_bits* positions sorted in ascending order.
        """
        preamble = TemporalCloakConst.PREAMBLE_BITS
        available = list(range(preamble, total_gaps))
        rng = random.Random(key)
        rng.shuffle(available)
        return sorted(available[:num_remaining_bits])

    def generate_delays(self, image_size: int,
                        chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO,
                        key: int | None = None) -> list:
        """Generate the full delay list for distributed mode.

        Returns a list of length total_gaps where preamble delays occupy
        positions 0-31 (contiguous), message/checksum/end-boundary delays
        are placed at pseudo-random positions selected by a random key,
        and all other positions get neutral delay (BIT_1_TIME_DELAY).

        If *key* is provided it is used directly; otherwise a random
        8-bit key is generated.
        """
        if self._message_encoded is None:
            raise ValueError("Set the message property before calling generate_delays")

        msg_len = len(self._message_encoded)
        if msg_len > TemporalCloakConst.MAX_DISTRIBUTED_MSG_LEN:
            raise ValueError(
                f"Message too long for distributed mode "
                f"(max {TemporalCloakConst.MAX_DISTRIBUTED_MSG_LEN} chars)")

        total_gaps = math.ceil(image_size / chunk_size) - 1

        if key is None:
            key = random.randint(0, 255)
        self._dist_key = key

        # Build preamble bits: boundary (16) + key (8) + msg_len (8)
        preamble_bits = BitArray(self.BOUNDARY)
        preamble_bits.append(BitArray(uint=key, length=TemporalCloakConst.DIST_KEY_BITS))
        preamble_bits.append(BitArray(uint=msg_len, length=TemporalCloakConst.DIST_LENGTH_BITS))

        # Remaining bits: message payload + checksum + end boundary
        remaining_data = BitArray(self._message_bits)
        checksum = TemporalCloakEncoding.compute_checksum(self._message_encoded)
        remaining_data.append(BitArray(uint=checksum, length=8))
        remaining_data.append(BitArray(self.BOUNDARY))

        num_remaining_bits = len(remaining_data)
        bit_positions = DistributedEncoder.compute_bit_positions(
            key, total_gaps, num_remaining_bits)

        # Build full delay list — filler gaps always use zero delay
        # (BIT_1_TIME_DELAY may be non-zero on internet deployments)
        delays = [0.0] * total_gaps

        # Place preamble delays at positions 0-31
        for i, bit in enumerate(preamble_bits):
            delays[i] = (TemporalCloakConst.BIT_1_TIME_DELAY if bit
                         else TemporalCloakConst.BIT_0_TIME_DELAY)

        # Place remaining data at selected positions
        data_idx = 0
        for pos in bit_positions:
            bit = remaining_data[data_idx]
            delays[pos] = (TemporalCloakConst.BIT_1_TIME_DELAY if bit
                           else TemporalCloakConst.BIT_0_TIME_DELAY)
            data_idx += 1

        self._delays = delays
        return delays

    @staticmethod
    def bits_required(message_len: int) -> int:
        """Total timing-delay slots including distributed preamble overhead."""
        boundary_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        return (boundary_bits * 2 + message_len * 8 + 8
                + TemporalCloakConst.DIST_KEY_BITS
                + TemporalCloakConst.DIST_LENGTH_BITS)

    @staticmethod
    def min_image_size(message_len: int,
                       chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> int:
        """Minimum image file size (bytes) to carry *message_len* characters."""
        total_bits = DistributedEncoder.bits_required(message_len)
        chunks_needed = total_bits + 1
        return (chunks_needed - 1) * chunk_size + 1

    @staticmethod
    def validate_image_size(image_size: int, message_len: int,
                            chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> bool:
        """Return True if image can carry the message."""
        available_chunks = math.ceil(image_size / chunk_size)
        available_slots = available_chunks - 1
        return available_slots >= DistributedEncoder.bits_required(message_len)

    @staticmethod
    def max_message_len(image_size: int,
                        chunk_size: int = TemporalCloakConst.CHUNK_SIZE_TORNADO) -> int:
        """Maximum message length (characters) this image can carry."""
        available_chunks = math.ceil(image_size / chunk_size)
        available_slots = available_chunks - 1
        boundary_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        overhead = (boundary_bits * 2 + 8
                    + TemporalCloakConst.DIST_KEY_BITS
                    + TemporalCloakConst.DIST_LENGTH_BITS)
        max_len = max(0, (available_slots - overhead) // 8)
        return min(max_len, TemporalCloakConst.MAX_DISTRIBUTED_MSG_LEN)

    @property
    def dist_key(self):
        return self._dist_key

    def _debug_preamble_sections(self, offset: int) -> tuple[list[dict], int]:
        key_bits = BitArray(uint=self._dist_key, length=TemporalCloakConst.DIST_KEY_BITS)
        msg_len_bits = BitArray(uint=len(self._message_encoded),
                                length=TemporalCloakConst.DIST_LENGTH_BITS)
        sections = [
            {
                "label": "dist_key",
                "bits": key_bits.bin,
                "value": self._dist_key,
                "offset": offset,
                "length": TemporalCloakConst.DIST_KEY_BITS,
            },
            {
                "label": "dist_msg_length",
                "bits": msg_len_bits.bin,
                "value": len(self._message_encoded),
                "offset": offset + TemporalCloakConst.DIST_KEY_BITS,
                "length": TemporalCloakConst.DIST_LENGTH_BITS,
            },
        ]
        new_offset = offset + TemporalCloakConst.DIST_KEY_BITS + TemporalCloakConst.DIST_LENGTH_BITS
        return sections, new_offset

    def _debug_preamble_bits(self) -> BitArray:
        result = BitArray()
        result.append(BitArray(uint=self._dist_key, length=TemporalCloakConst.DIST_KEY_BITS))
        result.append(BitArray(uint=len(self._message_encoded),
                               length=TemporalCloakConst.DIST_LENGTH_BITS))
        return result

    def __repr__(self):
        return f"DistributedEncoder(message='{self.message}')"
