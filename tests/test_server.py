import unittest
from unittest.mock import patch, MagicMock
from temporal_cloak.server import TemporalCloakServer


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


if __name__ == '__main__':
    unittest.main()
