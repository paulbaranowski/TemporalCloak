"""Hamming(12,8) forward error correction for TemporalCloak.

Encodes each 8-bit byte into a 12-bit codeword with 4 parity bits,
enabling single-bit error correction per block.

Codeword layout (1-indexed positions):

    Pos:  1   2   3   4   5   6   7   8   9  10  11  12
    Bit: p1  p2  d1  p4  d2  d3  d4  p8  d5  d6  d7  d8

Parity bits occupy positions that are powers of 2.  Each parity bit
covers positions whose binary index has that power-of-2 bit set:

    p1 (pos 1): covers 1,3,5,7,9,11
    p2 (pos 2): covers 2,3,6,7,10,11
    p4 (pos 4): covers 4,5,6,7,12
    p8 (pos 8): covers 8,9,10,11,12
"""

from bitstring import BitArray


def hamming_encode_byte(byte_val: int) -> BitArray:
    """Encode a single byte (8 data bits) into a 12-bit Hamming(12,8) codeword."""
    # Extract data bits (MSB first): d1..d8
    d = [(byte_val >> (7 - i)) & 1 for i in range(8)]
    # d[0]=d1, d[1]=d2, ..., d[7]=d8

    # Place data bits at non-power-of-2 positions (1-indexed: 3,5,6,7,9,10,11,12)
    # Build 12-bit array (0-indexed: positions 0..11 correspond to 1-indexed 1..12)
    block = [0] * 12
    block[2] = d[0]   # pos 3 = d1
    block[4] = d[1]   # pos 5 = d2
    block[5] = d[2]   # pos 6 = d3
    block[6] = d[3]   # pos 7 = d4
    block[8] = d[4]   # pos 9 = d5
    block[9] = d[5]   # pos 10 = d6
    block[10] = d[6]  # pos 11 = d7
    block[11] = d[7]  # pos 12 = d8

    # Compute parity bits
    # p1 (pos 1, 0-indexed 0): XOR of 1-indexed positions 1,3,5,7,9,11
    block[0] = block[2] ^ block[4] ^ block[6] ^ block[8] ^ block[10]
    # p2 (pos 2, 0-indexed 1): XOR of 1-indexed positions 2,3,6,7,10,11
    block[1] = block[2] ^ block[5] ^ block[6] ^ block[9] ^ block[10]
    # p4 (pos 4, 0-indexed 3): XOR of 1-indexed positions 4,5,6,7,12
    block[3] = block[4] ^ block[5] ^ block[6] ^ block[11]
    # p8 (pos 8, 0-indexed 7): XOR of 1-indexed positions 8,9,10,11,12
    block[7] = block[8] ^ block[9] ^ block[10] ^ block[11]

    return BitArray(block)


def hamming_decode_block(block: BitArray) -> tuple[int, int]:
    """Decode a 12-bit Hamming(12,8) codeword.

    Returns (corrected_byte_value, num_corrections).
    """
    if len(block) != 12:
        raise ValueError(f"Expected 12-bit block, got {len(block)}")

    b = [int(bit) for bit in block]

    # Compute syndrome bits (1-indexed parity checks)
    s1 = b[0] ^ b[2] ^ b[4] ^ b[6] ^ b[8] ^ b[10]   # pos 1,3,5,7,9,11
    s2 = b[1] ^ b[2] ^ b[5] ^ b[6] ^ b[9] ^ b[10]    # pos 2,3,6,7,10,11
    s4 = b[3] ^ b[4] ^ b[5] ^ b[6] ^ b[11]            # pos 4,5,6,7,12
    s8 = b[7] ^ b[8] ^ b[9] ^ b[10] ^ b[11]           # pos 8,9,10,11,12

    syndrome = s1 + (s2 << 1) + (s4 << 2) + (s8 << 3)

    corrections = 0
    if syndrome != 0:
        if syndrome > 12:
            # Syndrome points outside the block — uncorrectable (multi-bit error)
            corrections = 0
        else:
            # Flip the bit at the 1-indexed syndrome position (0-indexed: syndrome-1)
            b[syndrome - 1] ^= 1
            corrections = 1

    # Extract data bits from corrected block
    byte_val = (
        (b[2] << 7) |   # d1
        (b[4] << 6) |   # d2
        (b[5] << 5) |   # d3
        (b[6] << 4) |   # d4
        (b[8] << 3) |   # d5
        (b[9] << 2) |   # d6
        (b[10] << 1) |  # d7
        b[11]            # d8
    )

    return byte_val, corrections


def hamming_encode_message(data: bytes) -> BitArray:
    """Encode a byte sequence into concatenated 12-bit Hamming blocks."""
    result = BitArray()
    for byte_val in data:
        result.append(hamming_encode_byte(byte_val))
    return result


def hamming_decode_message(bits: BitArray) -> tuple[bytes, int, list[int]]:
    """Decode concatenated 12-bit Hamming blocks back to bytes.

    Returns (decoded_bytes, total_corrections, corrected_indices).
    corrected_indices is the list of block indices (0-based) that had a
    bit corrected.
    Raises ValueError if len(bits) is not a multiple of 12.
    """
    if len(bits) % 12 != 0:
        raise ValueError(
            f"Hamming payload ({len(bits)} bits) is not a multiple of 12"
        )

    result = bytearray()
    total_corrections = 0
    corrected_indices: list[int] = []
    for i in range(0, len(bits), 12):
        block = bits[i:i + 12]
        byte_val, corrections = hamming_decode_block(block)
        result.append(byte_val)
        total_corrections += corrections
        if corrections > 0:
            corrected_indices.append(i // 12)

    return bytes(result), total_corrections, corrected_indices
