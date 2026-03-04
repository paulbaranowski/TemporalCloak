from bitstring import Bits, BitStream, BitArray
from temporal_cloak.const import TemporalCloakConst
import time
import warnings


class TemporalCloakDecoding:
    BOUNDARY_LEN = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))

    def __init__(self, debug=False):
        self._bits = BitStream()
        self._time_delays = []
        self._eom = None
        self._last_message = None
        self._start_time = None
        self._last_recv_time = None
        self._debug = debug
        self._completed = False
        self._adaptive_threshold = None
        self._confidence_scores = []
        self._checksum_valid = None

    @property
    def bits(self) -> BitStream:
        return self._bits

    @property
    def completed(self) -> bool:
        return self._completed

    @property
    def checksum_valid(self):
        """True if last completed message passed checksum, False if failed, None if not yet checked."""
        return self._checksum_valid

    @property
    def threshold(self) -> float:
        """Return the adaptive threshold if calibrated, otherwise the fixed constant."""
        if self._adaptive_threshold is not None:
            return self._adaptive_threshold
        return TemporalCloakConst.MIDPOINT_TIME

    @property
    def confidence_scores(self) -> list:
        return self._confidence_scores

    def add_bit_by_delay(self, delay: float) -> None:
        self._time_delays.append(delay)
        threshold = self.threshold
        if delay <= threshold:
            self.add_bit(1)
        else:
            self.add_bit(0)
        # Track confidence: how far the delay is from the decision boundary
        distance = abs(delay - threshold)
        confidence = min(distance / threshold, 1.0) if threshold > 0 else 1.0
        self._confidence_scores.append(confidence)
        if confidence < 0.2:
            self.log(f"Low confidence bit at index {len(self._bits)-1}: "
                     f"delay={delay:.4f}s, threshold={threshold:.4f}s, confidence={confidence:.2f}")

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

    @staticmethod
    def verify_checksum(payload_bits, checksum_bits) -> bool:
        """Verify the 8-bit XOR checksum against the payload."""
        payload_bytes = payload_bits.tobytes()
        computed = 0
        for byte in payload_bytes:
            computed ^= byte
        return computed == checksum_bits.uint

    def decode(self, message, completed=False) -> str:
        """Decode message bits to string. If completed, the last 8 bits are
        treated as an XOR checksum and verified."""
        if completed and len(message) > 8:
            payload_bits = message[:-8]
            checksum_bits = message[-8:]
            if not self.verify_checksum(payload_bits, checksum_bits):
                warnings.warn("Checksum mismatch — message may be corrupted")
                self._checksum_valid = False
            else:
                self._checksum_valid = True
            message = payload_bits
        else:
            self._checksum_valid = None

        message_bytes = message.tobytes()
        try:
            decoded_message = message_bytes.decode('ascii')
        except UnicodeDecodeError:
            return ""
        self.log(decoded_message)
        return decoded_message

    def calibrate_from_boundary(self) -> None:
        """Use the first boundary marker (0xFF00 = 8 ones then 8 zeros) as a
        calibration preamble. Compute the average observed delay for each group
        and set the adaptive threshold to their midpoint."""
        if len(self._time_delays) < self.BOUNDARY_LEN:
            return
        ones_delays = self._time_delays[0:8]    # 0xFF = 8 ones
        zeros_delays = self._time_delays[8:16]  # 0x00 = 8 zeros
        avg_one = sum(ones_delays) / len(ones_delays)
        avg_zero = sum(zeros_delays) / len(zeros_delays)
        self._adaptive_threshold = (avg_one + avg_zero) / 2.0
        self.log(f"Calibrated threshold: {self._adaptive_threshold:.4f}s "
                 f"(avg_one={avg_one:.4f}s, avg_zero={avg_zero:.4f}s)")
        # Re-classify all bits with the calibrated threshold
        self._bits = BitStream()
        self._confidence_scores = []
        for delay in self._time_delays:
            threshold = self._adaptive_threshold
            if delay <= threshold:
                self.add_bit(1)
            else:
                self.add_bit(0)
            distance = abs(delay - threshold)
            confidence = min(distance / threshold, 1.0) if threshold > 0 else 1.0
            self._confidence_scores.append(confidence)

    def bits_to_message(self):
        # Attempt calibration once we have enough bits for the boundary
        if self._adaptive_threshold is None and len(self._time_delays) >= self.BOUNDARY_LEN:
            self.calibrate_from_boundary()

        completed = False
        begin_pos = TemporalCloakDecoding.find_boundary(self._bits)
        if begin_pos is None:
            self._eom = None
            return "", False, None
        begin_pos += self.BOUNDARY_LEN
        end_pos = TemporalCloakDecoding.find_boundary(self._bits, begin_pos)
        if end_pos is not None:
            completed = True
            self._eom = end_pos
            message = self._bits[begin_pos:end_pos]
        else:
            self._eom = None
            message = self._bits[begin_pos:]

        # Bit alignment check
        if completed and len(message) % 8 != 0:
            warnings.warn(
                f"Message bits ({len(message)}) not aligned to 8-bit boundary. "
                f"Possible bit corruption."
            )

        decoded = self.decode(message, completed)
        if completed:
            self._last_message = decoded
        return decoded, completed, end_pos

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
        if not decode_attempt:
            # Empty message between consecutive boundaries — skip display
            self.jump_to_next_message()
            return
        print("Decoded message: {}".format(decode_attempt))
        total_time = time.monotonic() - self._start_time
        print("Total time: {}".format(total_time))
        print("bits/second: {}".format(len(decode_attempt) * 8 / total_time))
        # truncate the bits array and start again
        self.jump_to_next_message()

    def __str__(self):
        result = "Current bits: '{}'\n".format(self._bits)
        result += "Completed: {}\n".format(self._completed)
        return result

    def __repr__(self):
        return f"TemporalCloakDecoding(bits='{self._bits}', completed='{self._completed}')"
