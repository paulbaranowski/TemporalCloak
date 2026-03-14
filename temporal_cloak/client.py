import socket
import time
import random
from temporal_cloak.encoding import FrontloadedEncoder


class TemporalCloakClient:
    def __init__(self, host: str = '127.0.0.1', port: int = 1234, hamming: bool = False):
        self._host = host
        self._port = port
        self._sock = None
        self._cloak = FrontloadedEncoder(hamming=hamming)

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def connect(self) -> None:
        """Creates a socket and connects to the server."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self._host, self._port))

    def disconnect(self) -> None:
        """Closes the socket connection."""
        if self._sock:
            self._sock.close()
            self._sock = None

    def set_message(self, message: str) -> None:
        """Sets the secret message to be encoded and transmitted."""
        self._cloak.message = message

    def send_sync_byte(self) -> None:
        """Sends a sync byte so the server can discard connection overhead."""
        self._send_byte_with_delay(0.1)

    def send(self) -> None:
        """Sends the encoded message once using time delays between bytes."""
        for delay in self._cloak.delays:
            self._send_byte_with_delay(delay)

    def _send_byte_with_delay(self, delay: float) -> None:
        """Sends a random byte then waits for the specified delay."""
        byte = bytes([random.randint(0, 255)])
        try:
            self._sock.sendall(byte)
            time.sleep(delay)
        except BrokenPipeError:
            self.disconnect()
            raise ConnectionError("Server closed the connection.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def __str__(self) -> str:
        return f"TemporalCloakClient(connected to {self._host}:{self._port})"

    def __repr__(self) -> str:
        return f"TemporalCloakClient(host='{self._host}', port={self._port})"
