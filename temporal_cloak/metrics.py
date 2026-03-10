"""Shared accuracy metrics for comparing decoded vs original messages."""


def compute_char_bit_errors(decoded_msg: str, original_msg: str) -> dict:
    """Count bit errors per character and return histogram buckets.

    Returns a dict with:
      - buckets: {0: N, 1: N, 2: N, ...} where key = bit errors, value = char count
      - per_char: list of (original_char, decoded_char, bit_errors) tuples
      - total_chars: total number of characters compared
    """
    if not decoded_msg or not original_msg:
        return {"buckets": {}, "per_char": [], "total_chars": 0}

    max_len = max(len(decoded_msg), len(original_msg))
    buckets = {}
    per_char = []

    for i in range(max_len):
        orig_c = original_msg[i] if i < len(original_msg) else None
        dec_c = decoded_msg[i] if i < len(decoded_msg) else None

        if orig_c is None or dec_c is None:
            # Missing character = 8 bit errors
            bit_errors = 8
        else:
            orig_bits = format(ord(orig_c), "08b")
            dec_bits = format(ord(dec_c), "08b")
            bit_errors = sum(1 for a, b in zip(orig_bits, dec_bits) if a != b)

        buckets[bit_errors] = buckets.get(bit_errors, 0) + 1
        per_char.append((orig_c or "?", dec_c or "?", bit_errors))

    return {"buckets": buckets, "per_char": per_char, "total_chars": max_len}
