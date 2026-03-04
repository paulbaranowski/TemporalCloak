import tornado.ioloop
import tornado.web
import time
from temporal_cloak.encoding import TemporalCloakEncoding
from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.quote_provider import QuoteProvider
from temporal_cloak.image_provider import ImageProvider
import humanize

quote_provider = QuoteProvider()
image_provider = ImageProvider()


class MainHandler(tornado.web.RequestHandler):
    async def get(self):
        print("Got request")
        self.set_header("Content-Type", "image/jpeg")

        image = image_provider.get_random_image()

        quote = quote_provider.get_encodable_quote()
        print(quote)
        cloak = TemporalCloakEncoding()
        cloak.message = quote
        delays = cloak.delays

        # Send the first chunk immediately (sync chunk — no encoded delay)
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
                    await tornado.ioloop.IOLoop.current().run_in_executor(None, time.sleep, delay)
                self.write(data)
                try:
                    await self.flush()
                except tornado.iostream.StreamClosedError:
                    break
        print("Sent {} ({})".format(image.path, humanize.naturalsize(image.size, True, False, "%.2f")))


if __name__ == "__main__":
    PORT = 8888
    print("Starting server on port {}".format(PORT))
    app = tornado.web.Application([
        (r"/", MainHandler),
    ])
    app.listen(PORT)
    tornado.ioloop.IOLoop.current().start()
