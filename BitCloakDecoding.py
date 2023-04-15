from bitstring import Bits, BitStream, BitArray
from BitCloakConst import BitCloakConst


class BitCloakDecoding:
    def __init__(self):
        self._bits = BitStream()
        self._time_delays = []
        self._eom = None
        self._last_message = None

    @property
    def bits(self):
        return self._bits

    def add_bit_by_delay(self, delay: float) -> None:
        self._time_delays.append(delay)
        # print(self._time_delays)
        if delay <= BitCloakConst.MIDPOINT_TIME:
            self.add_bit(1)
        else:
            self.add_bit(0)

    def add_bit(self, bit: bool) -> None:
        self._bits.append("0b{bit}".format(bit=bit))
        # print(self._bits.bin)

    def find_boundary(self, bits: BitStream, start_pos=0) -> int:
        boundary = Bits(BitCloakConst.BOUNDARY_BITS)
        # the "find" function returns a tuple which only has data in it if it was successful
        # it will return (<num>,) if it found something, otherwise ()
        pos = bits.find(boundary, start_pos)
        if len(pos) == 0:
            return None
        begin_pos = pos[0]
        return begin_pos

    def decode(self, message: str) -> str:
        message_bytes = message.tobytes()
        decoded_message = message_bytes.decode('ascii')
        return decoded_message

    def bits_to_message(self):
        completed = False
        begin_pos = self.find_boundary(self._bits)
        if begin_pos is None:
            self._eom = None
            return "", False, None
        begin_pos += len(BitArray(BitCloakConst.BOUNDARY_BITS))
        # print("Found boundary at {}".format(begin_pos))
        end_pos = self.find_boundary(self._bits, begin_pos)
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

    def jump_to_next_message(self):
        # print("EOM: {}".format(self._eom))
        self._bits = self._bits[self._eom:]
