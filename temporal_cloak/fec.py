"""Forward Error Correction codec abstraction.

Provides a uniform interface so the encoder/decoder can work with any FEC
scheme (Hamming, Reed-Solomon, etc.) without scattering codec-specific
conditionals throughout the pipeline.
"""

from __future__ import annotations

from bitstring import BitArray

from temporal_cloak.const import TemporalCloakConst


class FecCodec:
    """Abstract interface for a forward error correction codec.

    An FEC codec transforms raw payload bytes (message + checksum) into
    protected bit sequences and back.  The encoder calls ``encode_payload``
    before framing; the decoder calls ``decode_payload`` after extracting
    the payload from the frame.

    Attributes:
        block_size: Number of bits per encoded block (e.g. 12 for Hamming(12,8)).
    """

    block_size: int = 8  # base case: no FEC, 8 bits per byte

    def encode_payload(self, data: bytes) -> BitArray:
        """Encode raw bytes (message + checksum) into FEC-protected bits."""
        return BitArray(data)

    def decode_payload(self, bits: BitArray) -> tuple[bytes, int]:
        """Decode FEC-protected bits back to raw bytes.

        Returns (decoded_bytes, num_corrections).
        """
        return bits.tobytes(), 0

    def payload_bits(self, message_len: int) -> int:
        """Number of encoded bits for a message of *message_len* characters.

        Includes the checksum byte in the calculation.
        """
        return (message_len + 1) * self.block_size

    def validate_candidate(self, candidate_bits: BitArray) -> bool:
        """Check whether *candidate_bits* could be a valid FEC payload.

        Used by fuzzy boundary matching to filter false positives.
        Returns True if the candidate is block-aligned and its decoded
        checksum is valid.
        """
        if len(candidate_bits) < self.block_size:
            return False
        if len(candidate_bits) % self.block_size != 0:
            return False
        try:
            decoded_bytes, _ = self.decode_payload(candidate_bits)
        except (ValueError, Exception):
            return False
        if len(decoded_bytes) < 2:
            return False
        message_bytes = decoded_bytes[:-1]
        checksum_byte = decoded_bytes[-1]
        computed = 0
        for b in message_bytes:
            computed ^= b
        return computed == checksum_byte


class NoFec(FecCodec):
    """Identity codec — no forward error correction.

    Payload is raw message bits + 8-bit checksum, matching the original
    TemporalCloak wire format.
    """

    block_size = 8

    # TODO: Implement encode_payload, decode_payload, payload_bits,
    #       and validate_candidate for the no-FEC case.
    #
    # Guidance:
    #   - encode_payload: convert bytes to BitArray (straightforward)
    #   - decode_payload: convert BitArray to bytes, return 0 corrections
    #   - payload_bits: message_len * 8 + 8 (checksum)
    #   - validate_candidate: check 8-bit alignment + XOR checksum
    #
    # The base class already implements the right behavior for encode/decode.
    # You only need to override payload_bits and validate_candidate since the
    # no-FEC checksum layout differs (last 8 raw bits, not last decoded byte).

    def payload_bits(self, message_len: int) -> int:
        return message_len * 8 + 8

    def validate_candidate(self, candidate_bits: BitArray) -> bool:
        if len(candidate_bits) <= 8 or len(candidate_bits) % 8 != 0:
            return False
        payload = candidate_bits[:-8]
        checksum = candidate_bits[-8:]
        payload_bytes = payload.tobytes()
        computed = 0
        for b in payload_bytes:
            computed ^= b
        return computed == checksum.uint


class HammingFec(FecCodec):
    """Hamming(12,8) forward error correction codec.

    Each byte is encoded into a 12-bit codeword with 4 parity bits,
    enabling single-bit error correction per block.

    The checksum byte is Hamming-encoded alongside message bytes,
    so Hamming can correct errors in the checksum itself.
    """

    block_size = TemporalCloakConst.HAMMING_BLOCK_SIZE  # 12

    def encode_payload(self, data: bytes) -> BitArray:
        from temporal_cloak.hamming import hamming_encode_message
        return hamming_encode_message(data)

    def decode_payload(self, bits: BitArray) -> tuple[bytes, int]:
        from temporal_cloak.hamming import hamming_decode_message
        return hamming_decode_message(bits)
