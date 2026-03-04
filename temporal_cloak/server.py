import socket
from TemporalCloakDecoding import TemporalCloakDecoding


class TemporalCloakServer:
    def __init__(self, host: str = 'localhost', port: int = 1234, debug: bool = False):
        self._host = host
        self._port = port
        self._debug = debug
        self._listen_sock = None
        self._client_sock = None
        self._client_addr = None
        self._cloak = TemporalCloakDecoding(debug=debug)

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        """Binds and listens on the configured host and port."""
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.bind((self._host, self._port))
        self._listen_sock.listen(1)

    def stop(self) -> None:
        """Closes client and listener sockets."""
        if self._client_sock:
            self._client_sock.close()
            self._client_sock = None
        if self._listen_sock:
            self._listen_sock.close()
            self._listen_sock = None

    def accept_connection(self) -> None:
        """Waits for and accepts a single client connection."""
        print('waiting for a connection...')
        self._client_sock, self._client_addr = self._listen_sock.accept()
        print('client connected:', self._client_addr)

    def receive(self) -> None:
        """Receives bytes and decodes the hidden message from time delays."""
        # Discard the sync byte (connection overhead), then start timing
        self._receive_byte()
        self._cloak.start_timer()
        while True:
            if self._receive_byte():
                self._cloak.mark_time()
            else:
                break

    def _receive_byte(self) -> bool:
        """Receives a single byte from the client socket. Returns False on disconnect."""
        try:
            data = self._client_sock.recv(1)
            if not data:
                print("no data received")
                return False
            return True
        except (OSError, ConnectionResetError, ConnectionAbortedError) as e:
            print("Socket error:", e)
            return False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def __str__(self) -> str:
        return f"TemporalCloakServer(listening on {self._host}:{self._port})"

    def __repr__(self) -> str:
        return f"TemporalCloakServer(host='{self._host}', port={self._port}, debug={self._debug})"
