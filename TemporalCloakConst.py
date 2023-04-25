class TemporalCloakConst:
    # The time delay for a "1" bit
    BIT_1_TIME_DELAY = 0.00

    # The time delay for a "0" bit
    BIT_0_TIME_DELAY = 0.05

    # Due to network delays, the times sent will not be exact.
    # This is the value used to separate a bit "0" from a "1".
    MIDPOINT_TIME = 0.03

    # These are used to indicate the separation between messages.
    # If bits are dropped or missed, the message receiver can look
    # for these bits to reset itself.
    BOUNDARY_BITS = "0xFF00"

    # This is used for the size of the data chunk sent by the server.
    # Without chunking the data, the download speed will be too slow.
    CHUNK_SIZE_TORNADO = 4096
