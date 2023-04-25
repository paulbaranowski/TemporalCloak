from bitstring import Bits, BitStream, BitArray
from TemporalCloakConst import TemporalCloakConst
import time


class TemporalCloakDecoding:
    def __init__(self, debug=False):
        self._bits = BitStream()
        self._time_delays = []
        self._eom = None
        self._last_message = None
        self._start_time = None
        self._last_recv_time = None
        self._debug = debug
        self._completed = False

    @property
    def bits(self) -> BitStream:
        return self._bits

    @property
    def completed(self) -> bool:
        return self._completed

    def add_bit_by_delay(self, delay: float) -> None:
        self._time_delays.append(delay)
        # print(self._time_delays)
        if delay <= TemporalCloakConst.MIDPOINT_TIME:
            self.add_bit(1)
        else:
            self.add_bit(0)

    # @param bit must be 1 or 0
    def add_bit(self, bit: int) -> None:
        if bit in [0, 1]:
            self._bits.append("0b{bit}".format(bit=bit))
        else:
            raise ValueError("add_bit: argument 'bit' should be 1 or 0")

    # bits must be in the format "0b..."
    def add_bits(self, bits: str) -> None:
        self._bits.append(bits)

    @staticmethod
    def find_boundary(bits: BitStream, start_pos=0) -> int:
        boundary = Bits(TemporalCloakConst.BOUNDARY_BITS)
        # the "find" function returns a tuple which only has data in it if it was successful
        # it will return (<num>,) if it found something, otherwise ()
        pos = bits.find(boundary, start_pos)
        if len(pos) == 0:
            return None
        begin_pos = pos[0]
        return begin_pos

    def decode(self, message: str) -> str:
        message_bytes = message.tobytes()
        try:
            decoded_message = message_bytes.decode('ascii')
        except UnicodeDecodeError:
            return ""
        self.log(decoded_message)
        return decoded_message

    def bits_to_message(self):
        completed = False
        begin_pos = TemporalCloakDecoding.find_boundary(self._bits)
        if begin_pos is None:
            self._eom = None
            return "", False, None
        begin_pos += len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        # print("Found boundary at {}".format(begin_pos))
        end_pos = TemporalCloakDecoding.find_boundary(self._bits, begin_pos)
        if end_pos is not None:
            # print('found end pos {}'.format(end_pos))
            completed = True
            self._eom = end_pos
            message = self._bits[begin_pos:end_pos]
        else:
            self._eom = None
            message = self._bits[begin_pos:]
        self._last_message = self.decode(message)
        return self._last_message, completed, end_pos

    def jump_to_next_message(self) -> None:
        # print("EOM: {}".format(self._eom))
        self._bits = self._bits[self._eom:]

    # Call this when you get the first chunk of data
    def start_timer(self) -> None:
        self._start_time = self._last_recv_time = time.monotonic()

    def log(self, msg):
        if self._debug:
            print(msg)

    # call this when you get a chunk of data
    # it automatically adds the bit to the received message
    # will automatically print out the message if it finds a completed message
    def mark_time(self) -> float:
        # Get the current time
        current_time = time.monotonic()
        # Calculate the time difference between the current and last received byte
        time_diff = current_time - self._last_recv_time
        # Update last received time
        self._last_recv_time = current_time
        # Add the bit to the message
        self.add_bit_by_delay(time_diff)
        #self.log(self._bits.bin)
        # Try to decode the message
        decode_attempt, self._completed, end_pos = self.bits_to_message()
        # print(decode_attempt)
        if self._completed:
            # we got the whole message!
            self.display_completed(decode_attempt)
        # Return time difference
        return time_diff

    def display_completed(self, decode_attempt: str) -> None:
        print("Decoded message: {}".format(decode_attempt))
        total_time = time.monotonic() - self._start_time
        print("Total time: {}".format(total_time))
        print("bits/second: {}".format(len(decode_attempt) * 8 / total_time))
        start_time = time.monotonic()
        # truncate the bits array and start again
        self.jump_to_next_message()

    def __str__(self):
        result = "Current bits: '{}'\n".format(self._bits)
        result += "Completed: {}\n".format(self._completed)
        return result

    def __repr__(self):
        return f"TemporalCloakDecoding(bits='{self._bits}', completed='{self._completed}')"
