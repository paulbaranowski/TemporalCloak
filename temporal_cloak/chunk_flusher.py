import socket

import tornado.iostream
import tornado.web


class ChunkFlusher:
    """Controls precise chunk-level TCP transmission for timing steganography.

    Disables Nagle's algorithm and uses TCP_CORK (Linux) to ensure each
    chunk is sent as its own TCP segment with precise timing boundaries.
    Falls back gracefully on platforms without TCP_CORK (e.g. macOS).
    """

    _TCP_CORK = getattr(socket, "TCP_CORK", None)

    def __init__(self, handler: tornado.web.RequestHandler):
        self._handler = handler
        self._sock = None
        try:
            handler.request.connection.stream.set_nodelay(True)
        except AttributeError:
            pass
        try:
            self._sock = handler.request.connection.stream.socket
        except AttributeError:
            pass

    def cork(self):
        """Hold data in the kernel send buffer until uncork."""
        if self._TCP_CORK is not None and self._sock is not None:
            try:
                self._sock.setsockopt(socket.IPPROTO_TCP, self._TCP_CORK, 1)
            except OSError:
                pass

    def uncork(self):
        """Flush the kernel send buffer, pushing the chunk onto the wire."""
        if self._TCP_CORK is not None and self._sock is not None:
            try:
                self._sock.setsockopt(socket.IPPROTO_TCP, self._TCP_CORK, 0)
            except OSError:
                pass

    async def send(self, data: bytes) -> bool:
        """Cork, write, flush, uncork. Returns False if the client disconnected."""
        self.cork()
        self._handler.write(data)
        try:
            await self._handler.flush()
        except tornado.iostream.StreamClosedError:
            return False
        self.uncork()
        return True
