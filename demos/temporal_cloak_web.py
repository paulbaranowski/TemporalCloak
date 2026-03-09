import logging
import math
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
from temporal_cloak.encoding import FrontloadedEncoder, DistributedEncoder
from temporal_cloak.decoding import AutoDecoder, TemporalCloakDecoding
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.quote_provider import QuoteProvider
from temporal_cloak.image_provider import ImageProvider
from temporal_cloak.link_store import LinkStore

logger = logging.getLogger("temporalcloak")

quote_provider = QuoteProvider(quotes_path=config.QUOTES_PATH)
image_provider = ImageProvider(images_dir=config.IMAGES_DIR)

start_time = time.monotonic()

link_store = LinkStore(config.DB_PATH)


def _set_nodelay(handler):
    """Disable Nagle's algorithm on the handler's connection for timing precision."""
    try:
        handler.request.connection.stream.set_nodelay(True)
    except AttributeError:
        pass


class ImageHandler(tornado.web.RequestHandler):
    """Streams a random image with a hidden quote encoded in chunk timing."""

    async def get(self):
        _set_nodelay(self)
        logger.info("Steganography request from %s", self.request.remote_ip)
        self.set_header("Content-Type", "image/jpeg")

        image = image_provider.get_random_image()
        quote = quote_provider.get_encodable_quote()
        logger.info("Encoding quote: %s", quote)

        image_size = os.path.getsize(image.path)
        cloak = DistributedEncoder()
        cloak.message = quote
        distributed_delays = cloak.generate_delays(image_size)

        self.set_header("Content-Length", str(image_size))
        gap_index = 0
        first_chunk = True
        with open(image.path, "rb") as f:
            while True:
                data = f.read(TemporalCloakConst.CHUNK_SIZE_TORNADO)
                if not data:
                    break
                if first_chunk:
                    first_chunk = False
                else:
                    delay = distributed_delays[gap_index]
                    gap_index += 1
                    if delay > 0:
                        await asyncio.sleep(delay)
                self.write(data)
                try:
                    await self.flush()
                except tornado.iostream.StreamClosedError:
                    logger.warning("Client disconnected mid-stream")
                    break

        logger.info("Sent %s", image)


class ConfigHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "application/json")
        self.write({
            "bit_1_delay": TemporalCloakConst.BIT_1_TIME_DELAY,
            "bit_0_delay": TemporalCloakConst.BIT_0_TIME_DELAY,
            "midpoint": TemporalCloakConst.MIDPOINT_TIME,
        })

    def put(self):
        self.set_header("Content-Type", "application/json")
        try:
            body = tornado.escape.json_decode(self.request.body)
        except Exception:
            self.set_status(400)
            self.write({"error": "Invalid JSON body"})
            return

        allowed_keys = {"bit_1_delay", "bit_0_delay", "midpoint"}
        unknown_keys = set(body.keys()) - allowed_keys
        if unknown_keys:
            self.set_status(400)
            self.write({"error": f"Unknown keys: {', '.join(sorted(unknown_keys))}"})
            return

        if not body:
            self.set_status(400)
            self.write({"error": "No values provided"})
            return

        # Validate types: each value must be a non-negative number
        errors = []
        for key in ("bit_1_delay", "bit_0_delay", "midpoint"):
            if key in body:
                val = body[key]
                if not isinstance(val, (int, float)):
                    errors.append(f"{key} must be a number")
                elif val < 0:
                    errors.append(f"{key} must be non-negative")

        if errors:
            self.set_status(400)
            self.write({"error": "; ".join(errors)})
            return

        # Compute resulting values (merge provided with current)
        bit_1 = float(body.get("bit_1_delay", TemporalCloakConst.BIT_1_TIME_DELAY))
        bit_0 = float(body.get("bit_0_delay", TemporalCloakConst.BIT_0_TIME_DELAY))
        midpoint = float(body.get("midpoint", TemporalCloakConst.MIDPOINT_TIME))

        # Validate relationships
        if bit_1 >= bit_0:
            errors.append("bit_1_delay must be less than bit_0_delay")
        if midpoint <= bit_1 or midpoint >= bit_0:
            errors.append("midpoint must be between bit_1_delay and bit_0_delay")

        if errors:
            self.set_status(400)
            self.write({"error": "; ".join(errors)})
            return

        # Apply changes
        TemporalCloakConst.BIT_1_TIME_DELAY = bit_1
        TemporalCloakConst.BIT_0_TIME_DELAY = bit_0
        TemporalCloakConst.MIDPOINT_TIME = midpoint

        logger.info(
            "Timing config updated: bit_1=%.4f, bit_0=%.4f, midpoint=%.4f",
            bit_1, bit_0, midpoint,
        )

        self.write({
            "bit_1_delay": bit_1,
            "bit_0_delay": bit_0,
            "midpoint": midpoint,
        })


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
                        "thumbnail_url": f"/hosted/thumbnails/{fname}",
                        "size": file_size,
                        "max_message_len": DistributedEncoder.max_message_len(file_size),
                        "max_message_len_frontloaded": FrontloadedEncoder.max_message_len(file_size),
                        "max_message_len_distributed": DistributedEncoder.max_message_len(file_size),
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

        # Determine encoding mode
        mode = body.get("mode", "distributed")
        if mode not in ("frontloaded", "distributed"):
            self.set_status(400)
            self.write({"error": "Invalid mode (must be 'frontloaded' or 'distributed')"})
            return

        encoder_cls = FrontloadedEncoder if mode == "frontloaded" else DistributedEncoder

        # Validate image is large enough to carry the message
        image_size = os.path.getsize(real_image)
        if not encoder_cls.validate_image_size(image_size, len(message)):
            max_chars = encoder_cls.max_message_len(image_size)
            self.set_status(400)
            self.write({
                "error": f"Message too long for this image. "
                         f"This image can carry up to {max_chars} characters, "
                         f"but your message is {len(message)} characters. "
                         f"Try a shorter message or a larger image."
            })
            return

        burn_after_reading = bool(body.get("burn_after_reading", False))

        # Generate a PRNG key for distributed mode so it's consistent
        # across image serving and debug inspection.
        import random
        dist_key = random.randint(0, 255) if mode == "distributed" else None

        link_id = secrets.token_hex(4)
        link_store.create(
            link_id=link_id,
            message=message,
            image_path=image_path,
            image_filename=image_filename,
            created_at=time.time(),
            burn_after_reading=burn_after_reading,
            mode=mode,
            dist_key=dist_key,
        )
        logger.info(
            "Created link %s: message='%s', image='%s', burn=%s",
            link_id,
            message,
            image_filename,
            burn_after_reading,
        )

        self.set_header("Content-Type", "application/json")
        self.write({"id": link_id, "url": f"/view.html?id={link_id}"})


class LinkInfoHandler(tornado.web.RequestHandler):
    """Returns link metadata (without revealing the secret message)."""

    def get(self, link_id):
        link = link_store.get(link_id)
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
                "burn_after_reading": bool(link["burn_after_reading"]),
            }
        )


class EncodedImageHandler(tornado.web.RequestHandler):
    """Serves image with timing-encoded hidden message for a specific link."""

    async def get(self, link_id):
        _set_nodelay(self)
        link = link_store.get(link_id)
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

        image_size = os.path.getsize(link["image_path"])
        mode = link.get("mode", "distributed")

        if mode == "frontloaded":
            cloak = FrontloadedEncoder()
            cloak.message = link["message"]
            delays = list(cloak.delays)
        else:
            cloak = DistributedEncoder()
            cloak.message = link["message"]
            delays = cloak.generate_delays(image_size, key=link.get("dist_key"))

        self.set_header("Content-Length", str(image_size))
        gap_index = 0
        first_chunk = True
        with open(link["image_path"], "rb") as f:
            while True:
                data = f.read(TemporalCloakConst.CHUNK_SIZE_TORNADO)
                if not data:
                    break
                if first_chunk:
                    first_chunk = False
                elif gap_index < len(delays):
                    delay = delays[gap_index]
                    gap_index += 1
                    if delay > 0:
                        await asyncio.sleep(delay)
                self.write(data)
                try:
                    await self.flush()
                except tornado.iostream.StreamClosedError:
                    logger.warning("Client disconnected mid-stream (link %s)", link_id)
                    break

        logger.info("Sent encoded image for link %s", link_id)


class DebugLinkHandler(tornado.web.RequestHandler):
    """Returns the original message and full signal-bit sequence for a link."""

    def get(self, link_id):
        link = link_store.get(link_id)
        if not link:
            self.set_status(404)
            self.write({"error": "Link not found"})
            return

        message = link["message"]
        mode = link.get("mode", "distributed")
        image_size = os.path.getsize(link["image_path"])
        chunk_size = TemporalCloakConst.CHUNK_SIZE_TORNADO

        if mode == "frontloaded":
            encoder = FrontloadedEncoder()
            encoder.message = message
        else:
            encoder = DistributedEncoder()
            encoder.message = message
            encoder.generate_delays(image_size, key=link.get("dist_key"))

        signal = encoder.debug_signal_bits()
        total_gaps = math.ceil(image_size / chunk_size) - 1

        result = {
            "id": link_id,
            "message": message,
            "mode": mode,
            "image_filename": link["image_filename"],
            "image_size": image_size,
            "total_chunks": math.ceil(image_size / chunk_size),
            "total_gaps": total_gaps,
            "signal_bits": signal.bin,
            "signal_bits_hex": signal.hex,
            "signal_bit_count": len(signal),
            "sections": encoder.debug_sections(),
        }

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(result, indent=2))


class NormalImageHandler(tornado.web.RequestHandler):
    """Serves image without timing encoding (for display in <img> tags)."""

    def get(self, link_id):
        link = link_store.get(link_id)
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
            link = link_store.get(self.link_id)
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
        import math
        link = link_store.get(self.link_id)
        if not link:
            self._enqueue({"type": "error", "message": "Link not found"})
            self._enqueue(None)
            return

        try:
            protocol = "https" if config.TLS_CERT else "http"
            url = f"{protocol}://localhost:{config.PORT}/api/image/{self.link_id}"
            response = requests_lib.get(url, stream=True, verify=False)

            content_length = int(response.headers.get("Content-Length", 0))
            chunk_size = TemporalCloakConst.CHUNK_SIZE_TORNADO
            total_gaps = math.ceil(content_length / chunk_size) - 1 if content_length else 0

            decoder = AutoDecoder(total_gaps)
            boundary_len = TemporalCloakDecoding.BOUNDARY_LEN

            first_chunk = True
            decode_start = None
            prev_bit_count = 0
            total_bytes = 0

            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue

                total_bytes += len(chunk)

                if first_chunk:
                    now = time.monotonic()
                    decode_start = now
                    decoder.start_timer()
                    first_chunk = False
                    self._enqueue({
                        "type": "sync",
                        "timestamp": 0,
                        "content_length": content_length,
                    })
                    continue

                decoder.mark_time()
                elapsed = time.monotonic() - decode_start

                # Check if a new bit was actually added
                if decoder.bit_count > prev_bit_count:
                    prev_bit_count = decoder.bit_count

                    confidence = (
                        decoder.confidence_scores[-1]
                        if decoder.confidence_scores
                        else 1.0
                    )
                    bit_value = int(decoder.bits[-1])
                    bit_index = decoder.bit_count - 1

                    # Determine phase from bit position and detected mode
                    if decoder.mode == "distributed":
                        preamble_bits = TemporalCloakConst.PREAMBLE_BITS
                        if bit_index < boundary_len:
                            phase = "boundary_start"
                        elif bit_index < preamble_bits:
                            phase = "preamble"
                        else:
                            phase = "data"
                    else:
                        if bit_index < boundary_len:
                            phase = "boundary_start"
                        else:
                            phase = "data"

                    progress = total_bytes / content_length if content_length else 0
                    event = {
                        "type": "bit",
                        "index": bit_index,
                        "delay": round(decoder.last_delay, 6),
                        "bit": bit_value,
                        "confidence": round(confidence, 3),
                        "phase": phase,
                        "message_so_far": decoder.partial_message,
                        "threshold": round(decoder.threshold, 6),
                        "elapsed": round(elapsed, 3),
                        "progress": round(progress, 4),
                    }
                    if decoder.mode:
                        event["mode"] = decoder.mode
                    self._enqueue(event)
                else:
                    # Non-bit chunk — still send progress for image reveal
                    progress = total_bytes / content_length if content_length else 0
                    self._enqueue({
                        "type": "progress",
                        "progress": round(progress, 4),
                    })

                if decoder.message_complete:
                    self._enqueue(
                        {
                            "type": "complete",
                            "message": decoder.message,
                            "checksum_valid": decoder.checksum_valid,
                            "total_bits": decoder.bit_count,
                            "threshold": round(decoder.threshold, 6),
                            "elapsed": round(elapsed, 3),
                            "mode": decoder.mode,
                        }
                    )
                    link_store.mark_delivered(self.link_id)
                    break

            if not decoder.message_complete:
                msg, _, _ = decoder.bits_to_message()
                self._enqueue(
                    {
                        "type": "complete",
                        "message": msg,
                        "checksum_valid": False,
                        "total_bits": decoder.bit_count,
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
        (r"/api/image/([a-f0-9]+)/debug", DebugLinkHandler),
        (r"/api/image/([a-f0-9]+)/normal", NormalImageHandler),
        (r"/api/image/([a-f0-9]+)", EncodedImageHandler),
        (r"/api/decode/([a-f0-9]+)", DecodeWebSocketHandler),
        # Existing routes
        (r"/api/image", ImageHandler),
        (r"/api/config", ConfigHandler),
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
