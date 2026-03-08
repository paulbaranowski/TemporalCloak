_BIT_1_DELAY = 0.0
_BIT_0_DELAY = 0.30
_MIDPOINT = 0.15


class TemporalCloakConst:
    BIT_1_TIME_DELAY = _BIT_1_DELAY
    BIT_0_TIME_DELAY = _BIT_0_DELAY
    MIDPOINT_TIME = _MIDPOINT

    # These are used to indicate the separation between messages.
    # If bits are dropped or missed, the message receiver can look
    # for these bits to reset itself.
    BOUNDARY_BITS = "0xFF00"
    BOUNDARY_BITS_DISTRIBUTED = "0xFF01"

    # This is used for the size of the data chunk sent by the server.
    # Without chunking the data, the download speed will be too slow.
    CHUNK_SIZE_TORNADO = 256

    # Distributed mode constants
    # Preamble: 16 (boundary) + 8 (key) + 8 (message length) = 32 bits
    PREAMBLE_BITS = 32
    DIST_KEY_BITS = 8
    DIST_LENGTH_BITS = 8
    MAX_DISTRIBUTED_MSG_LEN = 255

