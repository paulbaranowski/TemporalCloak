import unittest
import warnings
import threading
import os
import json
import tempfile
from unittest.mock import patch, MagicMock
from TemporalCloakConst import TemporalCloakConst
from TemporalCloakDecoding import TemporalCloakDecoding
from TemporalCloakEncoding import TemporalCloakEncoding
from QuoteProvider import QuoteProvider
from ImageProvider import ImageProvider, ImageFile
from TemporalCloakClient import TemporalCloakClient
from TemporalCloakServer import TemporalCloakServer
from bitstring import Bits, BitArray, BitStream


def _checksum(msg_bytes):
    """Helper: compute 8-bit XOR checksum."""
    c = 0
    for b in msg_bytes:
        c ^= b
    return c


class TestTemporalCloakDecoding(unittest.TestCase):

    def setUp(self):
        self.decoding = TemporalCloakDecoding()
        # "hello" with checksum (0x62) + boundary markers, plus trailing bytes
        # Format: [0xFF00][68656c6c6f][62][FF00][6865]
        self.test_bits = BitStream('0xFF0068656c6c6f62FF006865')
        self.test_message = 'hello'

    def test_add_bit(self):
        self.decoding.add_bit(1)
        self.assertEqual(self.decoding.bits, BitStream('0b1'))

    def test_add_bit_by_delay(self):
        self.decoding.add_bit_by_delay(TemporalCloakConst.BIT_1_TIME_DELAY)
        self.assertEqual(self.decoding.bits, BitStream('0b1'))
        self.decoding.add_bit_by_delay(TemporalCloakConst.BIT_0_TIME_DELAY)
        self.assertEqual(self.decoding.bits, BitStream('0b10'))

    def test_find_boundary(self):
        result = self.decoding.find_boundary(self.test_bits)
        self.assertEqual(result, 0)

    def test_bits_to_message(self):
        self.decoding._bits = self.test_bits
        result, completed, end_pos = self.decoding.bits_to_message()
        self.assertEqual(result, self.test_message)
        self.assertTrue(completed)

    def test_jump_to_next_message(self):
        self.decoding._bits = self.test_bits
        self.decoding.bits_to_message()
        self.decoding.jump_to_next_message()
        self.assertEqual(self.decoding.bits, BitStream('0xFF006865'))


class TestFindBoundary(unittest.TestCase):
    def setUp(self):
        self.bits_with_boundary = BitArray('0b0101010101') + BitArray(TemporalCloakConst.BOUNDARY_BITS) + BitArray('0b0101010101')
        self.bits_with_two_boundaries = BitArray('0b0101010101') + BitArray(TemporalCloakConst.BOUNDARY_BITS) + BitArray('0b0101010101') + BitArray(TemporalCloakConst.BOUNDARY_BITS)
        self.bits_without_boundary = BitArray('0b0101010101010101010101010101')

    def test_boundary_found(self):
        result = TemporalCloakDecoding.find_boundary(self.bits_with_boundary)
        self.assertEqual(result, 10)

    def test_boundary_not_found(self):
        result = TemporalCloakDecoding.find_boundary(self.bits_without_boundary)
        self.assertIsNone(result)

    def test_two_boundaries(self):
        first = TemporalCloakDecoding.find_boundary(self.bits_with_two_boundaries)+1
        second = TemporalCloakDecoding.find_boundary(self.bits_with_two_boundaries, first)
        # 10 + 16 + 10 + 16 = 52
        self.assertEqual(second, 36)


class TestEndBoundary(unittest.TestCase):
    """Verify that the encoder produces both start and end boundary markers."""

    def test_encoded_message_has_both_boundaries(self):
        enc = TemporalCloakEncoding()
        enc.message = "hi"
        bits = enc._message_bits_padded
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        # Find first boundary
        pos1 = bits.find(boundary)
        self.assertTrue(len(pos1) > 0, "Start boundary not found")
        # Find second boundary after first
        pos2 = bits.find(boundary, pos1[0] + 1)
        self.assertTrue(len(pos2) > 0, "End boundary not found")


class TestSingleMessageCompletes(unittest.TestCase):
    """A single encoded message should decode as completed."""

    def test_single_message_completes(self):
        enc = TemporalCloakEncoding()
        enc.message = "test"
        decoder = TemporalCloakDecoding()
        # Feed all bits from the encoder directly into the decoder
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        result, completed, end_pos = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "test")


class TestEmptyMessageGuard(unittest.TestCase):
    """Double-boundary (empty message) should be handled gracefully."""

    def test_empty_message_between_boundaries(self):
        decoder = TemporalCloakDecoding()
        # Two boundaries back to back: [0xFF00][0xFF00]
        bits = BitStream(TemporalCloakConst.BOUNDARY_BITS + TemporalCloakConst.BOUNDARY_BITS)
        decoder._bits = bits
        result, completed, end_pos = decoder.bits_to_message()
        self.assertTrue(completed)
        # Should decode to empty string, and display_completed should not crash
        self.assertEqual(result, "")
        decoder.display_completed(result)  # should not raise


class TestBitAlignment(unittest.TestCase):
    """Non-multiple-of-8 bits between boundaries should produce a warning."""

    def test_misaligned_bits_warn(self):
        decoder = TemporalCloakDecoding()
        boundary = BitArray(TemporalCloakConst.BOUNDARY_BITS)
        # 5 bits of payload (not multiple of 8) + 8-bit checksum
        payload = BitArray('0b10101')
        checksum = BitArray(uint=0, length=8)
        bits = BitStream(boundary + payload + checksum + boundary)
        decoder._bits = bits
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            decoder.bits_to_message()
            alignment_warns = [x for x in w if "not aligned" in str(x.message)]
            self.assertTrue(len(alignment_warns) > 0, "Expected bit alignment warning")


class TestXORChecksum(unittest.TestCase):
    """Verify XOR checksum encoding and decoding."""

    def test_checksum_valid_on_good_message(self):
        enc = TemporalCloakEncoding()
        enc.message = "hello"
        decoder = TemporalCloakDecoding()
        for bit in enc._message_bits_padded:
            decoder.add_bit(int(bit))
        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "hello")
        self.assertTrue(decoder.checksum_valid)

    def test_checksum_detects_corruption(self):
        enc = TemporalCloakEncoding()
        enc.message = "hello"
        # Flip a bit in the message payload (after start boundary)
        corrupted = BitArray(enc._message_bits_padded)
        boundary_len = len(BitArray(TemporalCloakConst.BOUNDARY_BITS))
        flip_pos = boundary_len + 3  # flip a bit inside the payload
        corrupted.invert(flip_pos)
        decoder = TemporalCloakDecoding()
        for bit in corrupted:
            decoder.add_bit(int(bit))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result, completed, _ = decoder.bits_to_message()
            self.assertTrue(completed)
            checksum_warns = [x for x in w if "Checksum mismatch" in str(x.message)]
            self.assertTrue(len(checksum_warns) > 0, "Expected checksum mismatch warning")
        self.assertFalse(decoder.checksum_valid)


class TestAdaptiveThreshold(unittest.TestCase):
    """Verify adaptive threshold calibrates correctly with jittery delays."""

    def test_adaptive_threshold_with_jitter(self):
        enc = TemporalCloakEncoding()
        enc.message = "AB"
        decoder = TemporalCloakDecoding()

        # Simulate jitter: add +/-10ms noise to each delay
        import random
        random.seed(42)
        for delay in enc.delays:
            jittered = delay + random.uniform(-0.01, 0.01)
            jittered = max(0.0, jittered)  # clamp to non-negative
            decoder.add_bit_by_delay(jittered)

        result, completed, _ = decoder.bits_to_message()
        self.assertTrue(completed)
        self.assertEqual(result, "AB")
        # Adaptive threshold should have been calibrated
        self.assertIsNotNone(decoder._adaptive_threshold)


class TestDelaysReset(unittest.TestCase):
    """Setting message twice should only produce delays for the second message."""

    def test_delays_reset_on_reencode(self):
        enc = TemporalCloakEncoding()
        enc.message = "first"
        first_delays_len = len(enc.delays)
        enc.message = "hi"
        # Delays should correspond only to "hi" (not accumulated with "first")
        expected_bits = len(BitArray(TemporalCloakConst.BOUNDARY_BITS)) * 2 + len(BitArray(b'hi')) + 8  # +8 for checksum
        self.assertEqual(len(enc.delays), expected_bits)
        self.assertNotEqual(len(enc.delays), first_delays_len + expected_bits)


class TestBoundaryCollisionGuard(unittest.TestCase):
    """encode_message should assert on non-ASCII bytes."""

    def test_ascii_passes(self):
        success, encoded = TemporalCloakEncoding.encode_message("hello")
        self.assertTrue(success)
        self.assertEqual(encoded, b"hello")

    def test_non_ascii_fails(self):
        success, encoded = TemporalCloakEncoding.encode_message("caf\u00e9")
        self.assertFalse(success)


## ── QuoteProvider tests ──────────────────────────────────────────────


class TestQuoteProvider(unittest.TestCase):
    """Tests for QuoteProvider using the real quotes.json file."""

    def setUp(self):
        self.provider = QuoteProvider()

    def test_loads_quotes(self):
        self.assertGreater(self.provider.count, 0)

    def test_get_random_quote_returns_string(self):
        quote = self.provider.get_random_quote()
        self.assertIsInstance(quote, str)
        self.assertGreater(len(quote), 0)

    def test_get_random_quote_includes_author(self):
        # With 5000+ quotes, we'll find one with an author within a few tries
        found_author = False
        for _ in range(50):
            quote = self.provider.get_random_quote()
            if " - " in quote:
                found_author = True
                break
        self.assertTrue(found_author, "No quote with author found in 50 tries")

    def test_get_encodable_quote_is_ascii(self):
        quote = self.provider.get_encodable_quote()
        quote.encode('ascii')  # Should not raise

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            QuoteProvider(quotes_path="nonexistent.json")

    def test_str(self):
        s = str(self.provider)
        self.assertIn("QuoteProvider", s)
        self.assertIn("quotes", s)

    def test_repr(self):
        r = repr(self.provider)
        self.assertIn("QuoteProvider", r)
        self.assertIn("quotes_path=", r)


class TestQuoteProviderMinimal(unittest.TestCase):
    """Tests QuoteProvider with a controlled minimal JSON file."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='ascii'
        )
        json.dump([
            {"quoteText": "Hello world", "quoteAuthor": "Test"},
            {"quoteText": "Pure ascii", "quoteAuthor": ""},
        ], self.tmpfile)
        self.tmpfile.close()
        self.provider = QuoteProvider(quotes_path=self.tmpfile.name)

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def test_count(self):
        self.assertEqual(self.provider.count, 2)

    def test_quote_without_author_has_no_dash(self):
        # One of the two quotes has empty author
        found_no_dash = False
        for _ in range(20):
            quote = self.provider.get_random_quote()
            if " - " not in quote:
                found_no_dash = True
                break
        self.assertTrue(found_no_dash)


## ── ImageProvider tests ──────────────────────────────────────────────


class TestImageFile(unittest.TestCase):
    """Tests for the ImageFile dataclass."""

    def test_fields(self):
        img = ImageFile(path="/tmp/test.jpg", size=1024)
        self.assertEqual(img.path, "/tmp/test.jpg")
        self.assertEqual(img.size, 1024)

    def test_str_contains_path_and_size(self):
        img = ImageFile(path="content/images/photo.jpg", size=2048)
        s = str(img)
        self.assertIn("photo.jpg", s)
        self.assertIn("2.00 KiB" if "KiB" in s else "KB", s)


class TestImageProvider(unittest.TestCase):
    """Tests for ImageProvider using the real images directory."""

    def setUp(self):
        self.provider = ImageProvider()

    def test_get_random_image_returns_imagefile(self):
        image = self.provider.get_random_image()
        self.assertIsInstance(image, ImageFile)

    def test_image_has_valid_path(self):
        image = self.provider.get_random_image()
        self.assertTrue(os.path.isfile(image.path))

    def test_image_has_positive_size(self):
        image = self.provider.get_random_image()
        self.assertGreater(image.size, 0)

    def test_missing_directory_raises(self):
        provider = ImageProvider(images_dir="nonexistent/")
        with self.assertRaises(FileNotFoundError):
            provider.get_random_image()

    def test_str(self):
        self.assertIn("ImageProvider", str(self.provider))

    def test_repr(self):
        self.assertIn("images_dir=", repr(self.provider))


## ── TemporalCloakClient tests ────────────────────────────────────────


class TestTemporalCloakClientUnit(unittest.TestCase):
    """Unit tests for TemporalCloakClient (no real sockets)."""

    def test_defaults(self):
        client = TemporalCloakClient()
        self.assertEqual(client.host, '127.0.0.1')
        self.assertEqual(client.port, 1234)

    def test_custom_host_port(self):
        client = TemporalCloakClient(host='10.0.0.1', port=9999)
        self.assertEqual(client.host, '10.0.0.1')
        self.assertEqual(client.port, 9999)

    def test_disconnect_when_not_connected(self):
        client = TemporalCloakClient()
        client.disconnect()  # Should not raise

    def test_broken_pipe_raises_connection_error(self):
        client = TemporalCloakClient()
        mock_sock = MagicMock()
        mock_sock.sendall.side_effect = BrokenPipeError
        client._sock = mock_sock
        with self.assertRaises(ConnectionError):
            client._send_byte_with_delay(0.0)
        # Socket should be cleaned up
        self.assertIsNone(client._sock)

    def test_context_manager_connects_and_disconnects(self):
        with patch.object(TemporalCloakClient, 'connect') as mock_connect, \
             patch.object(TemporalCloakClient, 'disconnect') as mock_disconnect:
            with TemporalCloakClient() as client:
                mock_connect.assert_called_once()
            mock_disconnect.assert_called_once()

    def test_str(self):
        client = TemporalCloakClient()
        self.assertIn("127.0.0.1", str(client))
        self.assertIn("1234", str(client))

    def test_repr(self):
        r = repr(TemporalCloakClient(host='example.com', port=5555))
        self.assertIn("host='example.com'", r)
        self.assertIn("port=5555", r)


## ── TemporalCloakServer tests ────────────────────────────────────────


class TestTemporalCloakServerUnit(unittest.TestCase):
    """Unit tests for TemporalCloakServer (no real sockets)."""

    def test_defaults(self):
        server = TemporalCloakServer()
        self.assertEqual(server.host, 'localhost')
        self.assertEqual(server.port, 1234)

    def test_custom_host_port(self):
        server = TemporalCloakServer(host='0.0.0.0', port=8080, debug=True)
        self.assertEqual(server.host, '0.0.0.0')
        self.assertEqual(server.port, 8080)

    def test_stop_when_not_started(self):
        server = TemporalCloakServer()
        server.stop()  # Should not raise

    def test_context_manager_starts_and_stops(self):
        with patch.object(TemporalCloakServer, 'start') as mock_start, \
             patch.object(TemporalCloakServer, 'stop') as mock_stop:
            with TemporalCloakServer() as server:
                mock_start.assert_called_once()
            mock_stop.assert_called_once()

    def test_receive_byte_returns_false_on_empty(self):
        server = TemporalCloakServer()
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b''
        server._client_sock = mock_sock
        self.assertFalse(server._receive_byte())

    def test_receive_byte_returns_true_on_data(self):
        server = TemporalCloakServer()
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b'\x42'
        server._client_sock = mock_sock
        self.assertTrue(server._receive_byte())

    def test_receive_byte_returns_false_on_socket_error(self):
        server = TemporalCloakServer()
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = ConnectionResetError("reset")
        server._client_sock = mock_sock
        self.assertFalse(server._receive_byte())

    def test_str(self):
        self.assertIn("localhost", str(TemporalCloakServer()))

    def test_repr(self):
        r = repr(TemporalCloakServer(host='0.0.0.0', port=8080, debug=True))
        self.assertIn("host='0.0.0.0'", r)
        self.assertIn("debug=True", r)


## ── Client/Server integration test ──────────────────────────────────


class TestClientServerIntegration(unittest.TestCase):
    """End-to-end test: client sends a message, server decodes it."""

    def test_send_and_receive_message(self):
        message = "hi"
        port = 0  # Let OS assign a free port

        # Start server on OS-assigned port
        server = TemporalCloakServer(port=port)
        server.start()
        actual_port = server._listen_sock.getsockname()[1]

        decoded = {}

        def server_thread():
            server.accept_connection()
            server.receive()
            # _last_message is set during mark_time() → bits_to_message() → decode()
            # Note: _completed resets to False after jump_to_next_message() processes
            # subsequent bytes, so we check _last_message instead.
            decoded['message'] = server._cloak._last_message

        t = threading.Thread(target=server_thread)
        t.start()

        # Client sends the message
        client = TemporalCloakClient(port=actual_port)
        client.connect()
        client.set_message(message)
        client.send_sync_byte()
        client.send()
        client.disconnect()

        t.join(timeout=10)
        server.stop()

        self.assertEqual(decoded.get('message'), message,
                         "Server did not decode the correct message")


if __name__ == '__main__':
    unittest.main()
