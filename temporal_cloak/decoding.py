from bitstring import Bits, BitStream, BitArray
from temporal_cloak.const import TemporalCloakConst
import time
import warnings


class TemporalCloakDecoding:
    """Base decoder with shared bit manipulation, calibration, and message parsing.

    Subclasses implement mark_time() with mode-specific gap handling.
    """

    BOUNDARY = TemporalCloakConst.BOUNDARY_BITS
    BOUNDARY_LEN = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))

    # Extra bits after the start boundary before message payload begins.
    # FrontloadedDecoder: 0 (payload immediately follows boundary)
    # DistributedDecoder: 16 (key + length follow boundary)
    _preamble_extra_bits = 0

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
    def find_boundary(bits: BitStream, start_pos=0, boundary_hex=None) -> int:
        boundary = Bits(boundary_hex or TemporalCloakConst.BOUNDARY_BITS)
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
        begin_pos = TemporalCloakDecoding.find_boundary(self._bits, boundary_hex=self.BOUNDARY)
        if begin_pos is None:
            self._eom = None
            return "", False, None
        begin_pos += self.BOUNDARY_LEN
        # Skip any extra preamble bits (e.g. key + length in distributed mode)
        begin_pos += self._preamble_extra_bits
        end_pos = TemporalCloakDecoding.find_boundary(self._bits, begin_pos, boundary_hex=self.BOUNDARY)
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
        self._bits = self._bits[self._eom:]

    # Call this when you get the first chunk of data
    def start_timer(self) -> None:
        self._start_time = self._last_recv_time = time.monotonic()

    def log(self, msg):
        if self._debug:
            print(msg)

    def mark_time(self) -> float:
        """Record a timing gap and decode. Subclasses override for mode-specific logic."""
        raise NotImplementedError("Use FrontloadedDecoder or DistributedDecoder")

    def on_completed(self, decode_attempt: str) -> None:
        """Called when a complete message is decoded.

        Resets internal state to prepare for the next message.
        Override or attach a callback for custom display logic.
        """
        self.jump_to_next_message()

    def __str__(self):
        result = "Current bits: '{}'\n".format(self._bits)
        result += "Completed: {}\n".format(self._completed)
        return result

    def __repr__(self):
        return f"TemporalCloakDecoding(bits='{self._bits}', completed='{self._completed}')"


class FrontloadedDecoder(TemporalCloakDecoding):
    """Decodes messages where all bits are contiguous in the first N chunks.

    Every gap between chunks carries a real bit.
    """

    _preamble_extra_bits = 0

    def mark_time(self) -> float:
        current_time = time.monotonic()
        time_diff = current_time - self._last_recv_time
        self._last_recv_time = current_time

        self.add_bit_by_delay(time_diff)

        decode_attempt, self._completed, end_pos = self.bits_to_message()
        if self._completed:
            self.on_completed(decode_attempt)
        return time_diff

    def __repr__(self):
        return f"FrontloadedDecoder(bits='{self._bits}', completed='{self._completed}')"


class DistributedDecoder(TemporalCloakDecoding):
    """Decodes messages with bits scattered across chunks via a PRNG key.

    The first 32 gaps form a contiguous preamble (boundary + key + msg_len).
    After the preamble, only gaps at pseudo-randomly selected positions
    carry real bits; all other gaps are filler and are skipped.
    """

    BOUNDARY = TemporalCloakConst.BOUNDARY_BITS_DISTRIBUTED

    _preamble_extra_bits = (TemporalCloakConst.DIST_KEY_BITS
                            + TemporalCloakConst.DIST_LENGTH_BITS)

    def __init__(self, total_gaps: int, debug=False):
        super().__init__(debug)
        self._total_gaps = total_gaps
        self._gap_index = 0
        self._bit_positions = None
        self._preamble_collected = False

    def _process_preamble(self) -> None:
        """After collecting 32 preamble bits, extract key and message length,
        then compute bit positions for the remaining data."""
        from temporal_cloak.encoding import DistributedEncoder

        boundary_len = self.BOUNDARY_LEN

        # Calibrate from the boundary (bits 0-15)
        if self._adaptive_threshold is None and len(self._time_delays) >= boundary_len:
            self.calibrate_from_boundary()

        # Extract key (bits 16-23) and msg_len (bits 24-31)
        key = self._bits[boundary_len:boundary_len + TemporalCloakConst.DIST_KEY_BITS].uint
        preamble = TemporalCloakConst.PREAMBLE_BITS
        msg_len = self._bits[boundary_len + TemporalCloakConst.DIST_KEY_BITS:preamble].uint

        # Remaining bits: message payload + checksum (8) + end boundary (16)
        remaining_bits = msg_len * 8 + 8 + boundary_len

        self._bit_positions = set(
            DistributedEncoder.compute_bit_positions(
                key, self._total_gaps, remaining_bits)
        )
        self._preamble_collected = True
        self.log(f"Distributed preamble: key={key}, msg_len={msg_len}, "
                 f"remaining_bits={remaining_bits}, positions={len(self._bit_positions)}")

    def mark_time(self) -> float:
        current_time = time.monotonic()
        time_diff = current_time - self._last_recv_time
        self._last_recv_time = current_time

        gap_idx = self._gap_index
        self._gap_index += 1

        preamble = TemporalCloakConst.PREAMBLE_BITS
        if gap_idx < preamble:
            # Contiguous preamble — always process
            self.add_bit_by_delay(time_diff)
            if gap_idx == preamble - 1:
                self._process_preamble()
        elif self._bit_positions is not None and gap_idx in self._bit_positions:
            # This gap carries a real bit
            self.add_bit_by_delay(time_diff)
        else:
            # Filler gap — skip
            return time_diff

        # Don't try to decode until preamble is fully collected
        if not self._preamble_collected:
            return time_diff

        decode_attempt, self._completed, end_pos = self.bits_to_message()
        if self._completed:
            self.on_completed(decode_attempt)
        return time_diff

    def __repr__(self):
        return (f"DistributedDecoder(total_gaps={self._total_gaps}, "
                f"bits='{self._bits}', completed='{self._completed}')")


class AutoDecoder:
    """Auto-detects encoding mode from the boundary marker in the timing stream.

    Collects the first 16 timing delays (the boundary), checks the last bit
    to determine the mode, then delegates to the appropriate decoder.

    - Boundary 0xFF00 (bit 15 = 0) -> FrontloadedDecoder
    - Boundary 0xFF01 (bit 15 = 1) -> DistributedDecoder

    After bootstrapping, all subsequent calls are forwarded to the delegate.
    The replay feeds collected delays directly via add_bit_by_delay() to avoid
    timing issues with time.monotonic()-based mark_time().
    """

    def __init__(self, total_gaps: int, debug=False):
        self._total_gaps = total_gaps
        self._debug = debug
        self._bootstrap_delays = []
        self._delegate = None
        self._mode = None
        self._start_time = None
        self._last_recv_time = None
        self._bit_count = 0
        self._prev_bits_len = 0
        self._partial_high_water = ""

    @property
    def delegate(self):
        return self._delegate

    @property
    def mode(self):
        return self._mode

    @property
    def bits(self):
        if self._delegate:
            return self._delegate.bits
        return BitStream()

    @property
    def completed(self):
        if self._delegate:
            return self._delegate.completed
        return False

    @property
    def checksum_valid(self):
        if self._delegate:
            return self._delegate.checksum_valid
        return None

    @property
    def threshold(self):
        if self._delegate:
            return self._delegate.threshold
        return TemporalCloakConst.MIDPOINT_TIME

    @property
    def confidence_scores(self):
        if self._delegate:
            return self._delegate.confidence_scores
        return []

    @property
    def last_delay(self) -> float:
        """Most recent timing delay recorded by the delegate."""
        if self._delegate and self._delegate._time_delays:
            return self._delegate._time_delays[-1]
        return 0.0

    @property
    def time_delays(self) -> list:
        """All recorded timing delays from the delegate."""
        if self._delegate:
            return self._delegate._time_delays
        return []

    @property
    def boundary(self) -> str:
        """Boundary marker hex string used by the delegate."""
        if self._delegate:
            return self._delegate.BOUNDARY
        return TemporalCloakDecoding.BOUNDARY

    @property
    def boundary_len(self) -> int:
        """Length of the delegate's boundary marker in bits."""
        if self._delegate:
            return self._delegate.BOUNDARY_LEN
        return TemporalCloakDecoding.BOUNDARY_LEN

    @property
    def _last_message(self):
        if self._delegate:
            return self._delegate._last_message
        return None

    @property
    def bit_count(self) -> int:
        return self._bit_count

    @property
    def start_boundary_found(self) -> bool:
        """True once the start boundary has been detected (bootstrap complete)."""
        return self._delegate is not None

    @property
    def end_boundary_found(self) -> bool:
        """True once the end boundary has been found (message complete)."""
        return self.message_complete

    @property
    def bootstrap_progress(self) -> tuple[int, int]:
        """Progress toward detecting the start boundary: (collected, needed)."""
        needed = TemporalCloakDecoding.BOUNDARY_LEN
        if self._delegate is not None:
            return needed, needed
        return len(self._bootstrap_delays), needed

    @property
    def partial_message(self) -> str:
        """Stable partial message — only complete characters, preamble-aware.

        Uses a high-water mark so the result never shrinks. This prevents
        the message from disappearing while end-boundary bits arrive (the
        partial boundary bytes are non-ASCII, causing decode() to return "").
        """
        if not self._delegate or self._bit_count == 0:
            return self._partial_high_water
        if self._mode == "distributed":
            preamble = TemporalCloakConst.PREAMBLE_BITS
        else:
            preamble = TemporalCloakDecoding.BOUNDARY_LEN
        data_bits = self._bit_count - preamble if self._bit_count > preamble else 0
        if data_bits <= 0:
            return self._partial_high_water
        msg, _, _ = self.bits_to_message()
        if not msg:
            return self._partial_high_water
        complete_chars = data_bits // 8
        display_chars = max(0, complete_chars - 1)
        candidate = msg[:display_chars]
        if len(candidate) > len(self._partial_high_water):
            self._partial_high_water = candidate
        return self._partial_high_water

    @property
    def message(self) -> str:
        """Final message if complete, otherwise partial."""
        if self._delegate and self._delegate._last_message:
            return self._delegate._last_message
        return self.partial_message

    @property
    def message_complete(self) -> bool:
        """True when a full message has been decoded."""
        if self._delegate:
            return bool(self._delegate._last_message)
        return False

    def start_timer(self):
        self._start_time = time.monotonic()
        self._last_recv_time = self._start_time

    def bits_to_message(self):
        if self._delegate:
            return self._delegate.bits_to_message()
        return "", False, None

    def mark_time(self) -> float:
        current_time = time.monotonic()
        time_diff = current_time - self._last_recv_time
        self._last_recv_time = current_time

        if self._delegate is not None:
            # Already bootstrapped — forward directly
            self._delegate._last_recv_time = current_time - time_diff
            self._delegate.mark_time()
            self._track_bit_count()
            return time_diff

        # Still collecting boundary bits
        self._bootstrap_delays.append(time_diff)

        boundary_len = TemporalCloakDecoding.BOUNDARY_LEN
        if len(self._bootstrap_delays) < boundary_len:
            return time_diff

        # We have 16 delays — determine mode from the last bit
        ones_delays = self._bootstrap_delays[0:8]
        zeros_delays = self._bootstrap_delays[8:16]
        avg_one = sum(ones_delays) / len(ones_delays)
        avg_zero = sum(zeros_delays) / len(zeros_delays)
        threshold = (avg_one + avg_zero) / 2.0

        last_bit = 1 if self._bootstrap_delays[-1] <= threshold else 0

        if last_bit == 1:
            self._mode = "distributed"
            self._delegate = DistributedDecoder(self._total_gaps, debug=self._debug)
        else:
            self._mode = "frontloaded"
            self._delegate = FrontloadedDecoder(debug=self._debug)

        # Replay collected delays into the delegate directly via add_bit_by_delay.
        # This avoids timing issues since mark_time() uses time.monotonic().
        self._delegate._start_time = self._start_time or current_time
        self._delegate._last_recv_time = self._delegate._start_time
        for i, delay in enumerate(self._bootstrap_delays):
            self._delegate.add_bit_by_delay(delay)
            if self._mode == "distributed":
                self._delegate._gap_index += 1
                if self._delegate._gap_index == TemporalCloakConst.PREAMBLE_BITS:
                    self._delegate._process_preamble()

        # After bootstrap replay, set bit count to match replayed bits
        self._bit_count = len(self._delegate.bits)
        self._prev_bits_len = self._bit_count

        return time_diff

    def _track_bit_count(self):
        """Update bit count if the delegate's bitstream grew."""
        new_len = len(self._delegate.bits)
        if new_len > self._prev_bits_len:
            self._prev_bits_len = new_len
            self._bit_count += 1

    def __repr__(self):
        return (f"AutoDecoder(mode={self._mode!r}, "
                f"delegate={self._delegate!r})")
