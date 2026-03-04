import os


class TemporalCloakConst:
    # The time delay for a "1" bit
    # Localhost default: 0.00s. For internet deployment, set TC_BIT_1_DELAY=0.05
    BIT_1_TIME_DELAY = float(os.getenv("TC_BIT_1_DELAY", "0.00"))

    # The time delay for a "0" bit
    # Localhost default: 0.10s. For internet deployment, set TC_BIT_0_DELAY=0.30
    BIT_0_TIME_DELAY = float(os.getenv("TC_BIT_0_DELAY", "0.10"))

    # Due to network delays, the times sent will not be exact.
    # This is the value used to separate a bit "0" from a "1".
    # Localhost default: 0.05s. For internet deployment, set TC_MIDPOINT=0.175
    MIDPOINT_TIME = float(os.getenv("TC_MIDPOINT", "0.05"))

    # These are used to indicate the separation between messages.
    # If bits are dropped or missed, the message receiver can look
    # for these bits to reset itself.
    BOUNDARY_BITS = "0xFF00"

    # This is used for the size of the data chunk sent by the server.
    # Without chunking the data, the download speed will be too slow.
    CHUNK_SIZE_TORNADO = 256

