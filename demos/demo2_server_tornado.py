import logging
import ssl
import time
import sys
import os

import tornado.ioloop
import tornado.web
import tornado.httpserver

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from temporal_cloak.encoding import TemporalCloakEncoding
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.quote_provider import QuoteProvider
from temporal_cloak.image_provider import ImageProvider

logger = logging.getLogger("temporalcloak")

quote_provider = QuoteProvider(quotes_path=config.QUOTES_PATH)
image_provider = ImageProvider(images_dir=config.IMAGES_DIR)

start_time = time.monotonic()


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


def make_app():
    routes = [
        (r"/api/image", ImageHandler),
        (r"/api/health", HealthHandler),
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

        # HTTP → HTTPS redirect on port 80
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
