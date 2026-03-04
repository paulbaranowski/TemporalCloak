import logging
import ssl
import time
import sys
import os
import json
import secrets
import asyncio

import tornado.ioloop
import tornado.web
import tornado.httpserver
import tornado.websocket
import requests as requests_lib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from temporal_cloak.encoding import TemporalCloakEncoding
from temporal_cloak.decoding import TemporalCloakDecoding
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.quote_provider import QuoteProvider
from temporal_cloak.image_provider import ImageProvider

logger = logging.getLogger("temporalcloak")

quote_provider = QuoteProvider(quotes_path=config.QUOTES_PATH)
image_provider = ImageProvider(images_dir=config.IMAGES_DIR)

start_time = time.monotonic()

# In-memory link storage: {link_id: {message, image_path, image_filename, created_at}}
links = {}


class ImageHandler(tornado.web.RequestHandler):
    """Streams a random image with a hidden quote encoded in chunk timing."""

    async def get(self):
        logger.info("Steganography request from %s", self.request.remote_ip)
        self.set_header("Content-Type", "image/jpeg")

        image = image_provider.get_random_image()
        quote = quote_provider.get_encodable_quote()
        logger.info("Encoding quote: %s", quote)

        cloak = TemporalCloakEncoding()
        cloak.message = quote
        delays = cloak.delays

        first_chunk = True
        with open(image.path, "rb") as f:
            while True:
                data = f.read(TemporalCloakConst.CHUNK_SIZE_TORNADO)
                if not data:
                    break
                if first_chunk:
                    first_chunk = False
                elif len(delays) > 0:
                    delay = delays.pop(0)
                    await tornado.ioloop.IOLoop.current().run_in_executor(
                        None, time.sleep, delay
                    )
                self.write(data)
                try:
                    await self.flush()
                except tornado.iostream.StreamClosedError:
                    logger.warning("Client disconnected mid-stream")
                    break

        logger.info("Sent %s", image)


class HealthHandler(tornado.web.RequestHandler):
    def get(self):
        uptime = int(time.monotonic() - start_time)
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok", "uptime": uptime})


class RedirectHandler(tornado.web.RequestHandler):
    def get(self):
        self.redirect(
            f"https://{self.request.host}{self.request.uri}", permanent=True
        )


# ---------------------------------------------------------------------------
# New handlers for the web demo
# ---------------------------------------------------------------------------


class ImageListHandler(tornado.web.RequestHandler):
    """Returns JSON list of available hosted images."""

    def get(self):
        images = []
        for fname in sorted(os.listdir(config.IMAGES_DIR)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                fpath = os.path.join(config.IMAGES_DIR, fname)
                file_size = os.path.getsize(fpath)
                images.append(
                    {
                        "filename": fname,
                        "url": f"/hosted/{fname}",
                        "size": file_size,
                        "max_message_len": TemporalCloakEncoding.max_message_len(file_size),
                    }
                )
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(images))


class CreateLinkHandler(tornado.web.RequestHandler):
    """Stores message + image and returns a shareable link ID."""

    def post(self):
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            self.set_status(400)
            self.write({"error": "Invalid JSON"})
            return

        message = body.get("message", "").strip()
        image_filename = body.get("image", "")

        if not message:
            self.set_status(400)
            self.write({"error": "Message is required"})
            return
        if len(message) > 200:
            self.set_status(400)
            self.write({"error": "Message too long (max 200 characters)"})
            return
        try:
            message.encode("ascii")
        except UnicodeEncodeError:
            self.set_status(400)
            self.write({"error": "Message must be ASCII only"})
            return

        # Validate image exists and prevent path traversal
        image_path = os.path.join(config.IMAGES_DIR, image_filename)
        real_image = os.path.realpath(image_path)
        real_dir = os.path.realpath(config.IMAGES_DIR)
        if not real_image.startswith(real_dir + os.sep) or not os.path.isfile(
            real_image
        ):
            self.set_status(400)
            self.write({"error": "Image not found"})
            return

        # Validate image is large enough to carry the message
        image_size = os.path.getsize(real_image)
        if not TemporalCloakEncoding.validate_image_size(image_size, len(message)):
            max_chars = TemporalCloakEncoding.max_message_len(image_size)
            self.set_status(400)
            self.write({
                "error": f"Message too long for this image. "
                         f"This image can carry up to {max_chars} characters, "
                         f"but your message is {len(message)} characters. "
                         f"Try a shorter message or a larger image."
            })
            return

        link_id = secrets.token_hex(4)
        links[link_id] = {
            "message": message,
            "image_path": image_path,
            "image_filename": image_filename,
            "created_at": time.time(),
        }
        logger.info(
            "Created link %s: message='%s', image='%s'",
            link_id,
            message,
            image_filename,
        )

        self.set_header("Content-Type", "application/json")
        self.write({"id": link_id, "url": f"/view.html?id={link_id}"})


class LinkInfoHandler(tornado.web.RequestHandler):
    """Returns link metadata (without revealing the secret message)."""

    def get(self, link_id):
        link = links.get(link_id)
        if not link:
            self.set_status(404)
            self.write({"error": "Link not found"})
            return
        self.set_header("Content-Type", "application/json")
        self.write(
            {
                "id": link_id,
                "image_filename": link["image_filename"],
                "created_at": link["created_at"],
                "has_message": True,
            }
        )


class EncodedImageHandler(tornado.web.RequestHandler):
    """Serves image with timing-encoded hidden message for a specific link."""

    async def get(self, link_id):
        link = links.get(link_id)
        if not link:
            self.set_status(404)
            self.write({"error": "Link not found"})
            return

        logger.info(
            "Encoded image request for link %s from %s",
            link_id,
            self.request.remote_ip,
        )
        self.set_header("Content-Type", "image/jpeg")

        cloak = TemporalCloakEncoding()
        cloak.message = link["message"]
        delays = cloak.delays

        first_chunk = True
        with open(link["image_path"], "rb") as f:
            while True:
                data = f.read(TemporalCloakConst.CHUNK_SIZE_TORNADO)
                if not data:
                    break
                if first_chunk:
                    first_chunk = False
                elif len(delays) > 0:
                    delay = delays.pop(0)
                    await tornado.ioloop.IOLoop.current().run_in_executor(
                        None, time.sleep, delay
                    )
                self.write(data)
                try:
                    await self.flush()
                except tornado.iostream.StreamClosedError:
                    logger.warning("Client disconnected mid-stream (link %s)", link_id)
                    break

        logger.info("Sent encoded image for link %s", link_id)


class NormalImageHandler(tornado.web.RequestHandler):
    """Serves image without timing encoding (for display in <img> tags)."""

    def get(self, link_id):
        link = links.get(link_id)
        if not link:
            self.set_status(404)
            self.write({"error": "Link not found"})
            return
        image_path = link["image_path"]
        ext = os.path.splitext(image_path)[1].lower()
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        self.set_header("Content-Type", content_types.get(ext, "image/jpeg"))
        with open(image_path, "rb") as f:
            self.write(f.read())


class DecodeWebSocketHandler(tornado.websocket.WebSocketHandler):
    """Streams real-time decode progress over WebSocket."""

    def check_origin(self, origin):
        return True

    def open(self, link_id):
        self.link_id = link_id
        self.queue = asyncio.Queue()
        self._loop = asyncio.get_event_loop()
        logger.info("WebSocket opened for link %s", link_id)

    async def on_message(self, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        if data.get("action") == "start":
            link = links.get(self.link_id)
            if not link:
                self.write_message(
                    json.dumps({"type": "error", "message": "Link not found"})
                )
                return

            # Launch decode in a background thread
            tornado.ioloop.IOLoop.current().run_in_executor(
                None, self._decode_thread
            )
            # Stream queued events to the client
            await self._send_events()

    async def _send_events(self):
        """Read from the async queue and forward to the WebSocket client."""
        while True:
            msg = await self.queue.get()
            if msg is None:
                break
            try:
                self.write_message(json.dumps(msg))
            except tornado.websocket.WebSocketClosedError:
                break

    def _decode_thread(self):
        """Fetch the encoded image and decode timing in a worker thread."""
        link = links.get(self.link_id)
        if not link:
            self._enqueue({"type": "error", "message": "Link not found"})
            self._enqueue(None)
            return

        try:
            protocol = "https" if config.TLS_CERT else "http"
            url = f"{protocol}://localhost:{config.PORT}/api/image/{self.link_id}"
            response = requests_lib.get(url, stream=True, verify=False)

            decoder = TemporalCloakDecoding()
            first_chunk = True
            bit_index = 0
            last_recv_time = None
            decode_start = None
            boundary_len = TemporalCloakDecoding.BOUNDARY_LEN
            stable_message = ""

            for chunk in response.iter_content(
                chunk_size=TemporalCloakConst.CHUNK_SIZE_TORNADO
            ):
                if not chunk:
                    continue

                if first_chunk:
                    last_recv_time = time.monotonic()
                    decode_start = last_recv_time
                    first_chunk = False
                    self._enqueue({"type": "sync", "timestamp": 0})
                    continue

                current_time = time.monotonic()
                time_diff = current_time - last_recv_time
                last_recv_time = current_time
                elapsed = current_time - decode_start

                decoder.add_bit_by_delay(time_diff)
                msg, completed, end_pos = decoder.bits_to_message()

                confidence = (
                    decoder.confidence_scores[-1]
                    if decoder.confidence_scores
                    else 1.0
                )
                bit_value = int(decoder.bits[-1])

                phase = "boundary_start" if bit_index < boundary_len else "data"

                # Only include fully-decoded characters (drop partial-byte
                # artifacts from tobytes() zero-padding).  Hold back the
                # last complete char — it might be the checksum byte,
                # which gets stripped on completion.
                if not completed and bit_index >= boundary_len:
                    complete_chars = (bit_index - boundary_len + 1) // 8
                    display_chars = max(0, complete_chars - 1)
                    truncated = msg[:display_chars]
                    if len(truncated) > len(stable_message):
                        stable_message = truncated

                event = {
                    "type": "bit",
                    "index": bit_index,
                    "delay": round(time_diff, 6),
                    "bit": bit_value,
                    "confidence": round(confidence, 3),
                    "phase": phase,
                    "message_so_far": stable_message,
                    "threshold": round(decoder.threshold, 6),
                    "elapsed": round(elapsed, 3),
                }
                self._enqueue(event)
                bit_index += 1

                if completed:
                    self._enqueue(
                        {
                            "type": "complete",
                            "message": msg,
                            "checksum_valid": decoder.checksum_valid,
                            "total_bits": bit_index,
                            "threshold": round(decoder.threshold, 6),
                            "elapsed": round(elapsed, 3),
                        }
                    )
                    break

            if not decoder.completed:
                msg, _, _ = decoder.bits_to_message()
                self._enqueue(
                    {
                        "type": "complete",
                        "message": msg,
                        "checksum_valid": False,
                        "total_bits": bit_index,
                        "elapsed": (
                            round(time.monotonic() - decode_start, 3)
                            if decode_start
                            else 0
                        ),
                        "partial": True,
                    }
                )
        except Exception as e:
            logger.error("Decode thread error: %s", e, exc_info=True)
            self._enqueue({"type": "error", "message": str(e)})
        finally:
            self._enqueue(None)

    def _enqueue(self, data):
        """Thread-safe: push an event onto the async queue."""
        asyncio.run_coroutine_threadsafe(self.queue.put(data), self._loop)

    def on_close(self):
        logger.info("WebSocket closed for link %s", self.link_id)


def make_app():
    routes = [
        # New web-demo routes
        (r"/api/images", ImageListHandler),
        (r"/api/create", CreateLinkHandler),
        (r"/api/link/([a-f0-9]+)", LinkInfoHandler),
        (r"/api/image/([a-f0-9]+)/normal", NormalImageHandler),
        (r"/api/image/([a-f0-9]+)", EncodedImageHandler),
        (r"/api/decode/([a-f0-9]+)", DecodeWebSocketHandler),
        # Existing routes
        (r"/api/image", ImageHandler),
        (r"/api/health", HealthHandler),
        # Serve hosted images (content/images) for the thumbnail picker
        (
            r"/hosted/(.*)",
            tornado.web.StaticFileHandler,
            {"path": config.IMAGES_DIR},
        ),
    ]

    if os.path.isdir(config.STATIC_DIR):
        # Serve landing page at / from static/index.html
        routes.append(
            (
                r"/(.*)",
                tornado.web.StaticFileHandler,
                {"path": config.STATIC_DIR, "default_filename": "index.html"},
            )
        )

    return tornado.web.Application(routes)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = make_app()

    if config.TLS_CERT and config.TLS_KEY:
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(
            certfile=config.TLS_CERT, keyfile=config.TLS_KEY
        )
        server = tornado.httpserver.HTTPServer(app, ssl_options=ssl_ctx)
        server.listen(config.PORT, address=config.HOST)
        logger.info(
            "HTTPS server listening on %s:%d", config.HOST, config.PORT
        )

        # HTTP -> HTTPS redirect on port 80
        redirect_app = tornado.web.Application([(r"/.*", RedirectHandler)])
        redirect_app.listen(80, address=config.HOST)
        logger.info("HTTP redirect listening on %s:80", config.HOST)
    else:
        app.listen(config.PORT, address=config.HOST)
        logger.info(
            "HTTP server listening on %s:%d (no TLS)", config.HOST, config.PORT
        )

    logger.info(
        "Timing: BIT_1=%.3fs, BIT_0=%.3fs, MIDPOINT=%.3fs",
        TemporalCloakConst.BIT_1_TIME_DELAY,
        TemporalCloakConst.BIT_0_TIME_DELAY,
        TemporalCloakConst.MIDPOINT_TIME,
    )

    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
