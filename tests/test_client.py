import unittest
from unittest.mock import patch, MagicMock
from temporal_cloak.client import TemporalCloakClient


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


if __name__ == '__main__':
    unittest.main()
