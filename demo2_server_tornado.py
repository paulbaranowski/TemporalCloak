import tornado.ioloop
import tornado.web
import time
import os
import random
import json
from TemporalCloakEncoding import TemporalCloakEncoding
from TemporalCloakConst import TemporalCloakConst
import humanize


def get_random_quote() -> str:
    # Open the file in read mode
    f2 = open("content/quotes/quotes.json", "r", encoding="Windows-1252")
    # Load the JSON data from the file
    data = json.load(f2)

    # Pick a random quote from the list
    random_quote = random.choice(data)

    # Extract the quote text and author from the chosen quote
    quote_text = random_quote["quoteText"]
    quote_author = random_quote["quoteAuthor"]
    if quote_author.strip() != "":
        quote_author = " - "+quote_author
    # Display the chosen quote
    return f"{quote_text}{quote_author}"


def get_random_file() -> str:
    directory = "content/images/"  # replace with your directory path
    files = os.listdir(directory)
    random_file = random.choice(files)
    full_path = os.path.join(directory, random_file)
    file_size = os.path.getsize(full_path)
    print("Size: {}  Path: {}".format(humanize.naturalsize(file_size, True, False,  "%.2f"), full_path))
    return full_path, file_size


class MainHandler(tornado.web.RequestHandler):
    async def get(self):
        print("Got request")
        # Set the content type header to indicate that the response is an image
        self.set_header("Content-Type", "image/jpeg")

        # Open the image file as binary data
        full_path, file_size = get_random_file()
        f = open(full_path, "rb")

        # Get a random quote - sometimes encoding in the file is messed up so we need to keep trying
        got_quote = False
        while not got_quote:
            quote = get_random_quote()
            got_quote, _ = TemporalCloakEncoding.encode_message(quote)

        print(quote)
        cloak = TemporalCloakEncoding()
        cloak.message = quote
        delays = cloak.delays

        while True:
            bytes = f.read(TemporalCloakConst.CHUNK_SIZE_TORNADO)
            if not bytes:
                break
            if len(delays) > 0:
                delay = delays.pop(0)
                await tornado.ioloop.IOLoop.current().run_in_executor(None, time.sleep, delay)
            self.write(bytes)
            try:
                await self.flush()
            except tornado.iostream.StreamClosedError:
                break
        print("Sent {} ({})".format(full_path, humanize.naturalsize(file_size, True, False, "%.2f")))


if __name__ == "__main__":
    PORT = 8888
    print("Starting server on port {}".format(PORT))
    app = tornado.web.Application([
        (r"/", MainHandler),
    ])
    app.listen(PORT)
    tornado.ioloop.IOLoop.current().start()