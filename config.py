import os

HOST = os.getenv("TC_HOST", "0.0.0.0")
PORT = int(os.getenv("TC_PORT", "8888"))
TLS_CERT = os.getenv("TC_TLS_CERT", "")
TLS_KEY = os.getenv("TC_TLS_KEY", "")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUOTES_PATH = os.path.join(BASE_DIR, "content", "quotes", "quotes.json")
IMAGES_DIR = os.path.join(BASE_DIR, "content", "images")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.getenv("TC_DB_PATH", os.path.join(BASE_DIR, "data", "links.db"))

# Timing: delay (in seconds) inserted between chunks to encode bits
BIT_1_DELAY = 0.0
BIT_0_DELAY = 0.10
MIDPOINT = 0.05
