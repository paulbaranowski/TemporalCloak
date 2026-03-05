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

# --- Production deployment values (Hostinger VPS) ---
# Set these as environment variables in the systemd service, or uncomment
# the overrides below to hardcode them.
#
# TC_HOST=0.0.0.0
# TC_PORT=443
# TC_TLS_CERT=/etc/letsencrypt/live/yourdomain.com/fullchain.pem
# TC_TLS_KEY=/etc/letsencrypt/live/yourdomain.com/privkey.pem
#
# Timing (wider gaps for internet jitter):
# TC_BIT_1_DELAY=0.05
# TC_BIT_0_DELAY=0.30
# TC_MIDPOINT=0.175
