# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TemporalCloak is a time-based steganography tool. It hides secret messages in the **timing delays** between data transmissions — not in the data content itself. Messages are encoded as bit sequences where each bit maps to a specific time delay (short delay = 1, longer delay = 0). A boundary marker (`0xFF00`) frames each message.

## Commands

```bash
# Setup (uses uv, not pip)
uv sync

# Run all tests (unittest, no pytest)
uv run python -m unittest discover -s tests -v

# Run a single test file
uv run python -m unittest tests.test_encoding -v

# Run a single test method
uv run python -m unittest tests.test_encoding.TestEncoding.test_encode_message -v

# Demo 1: Client sends hidden message to server via raw TCP sockets
uv run python demos/demo1_server.py   # start first, listens on localhost:1234
uv run python demos/demo1_client.py   # prompts for message, sends with timing encoding

# Demo 2: Server embeds hidden message in HTTP image response (Tornado)
uv run python demos/temporal_cloak_web_demo.py   # starts on localhost:8888
uv run python demos/temporal_cloak_cli_decoder.py # decodes hidden quote from chunk timing
```

## Architecture

### Core Package (`temporal_cloak/`)

- **TemporalCloakEncoding** (`encoding.py`) — Converts string → bit array → delay sequence. Prepends boundary bits. Used by senders.
- **TemporalCloakDecoding** (`decoding.py`) — Reconstructs messages from timing: accumulates bits via `mark_time()`, finds boundary markers, decodes bit stream back to text. Used by receivers.
- **TemporalCloakConst** (`const.py`) — Protocol constants (bit delays, midpoint threshold, boundary marker, chunk size). Timing values are configurable via `TC_BIT_1_DELAY`, `TC_BIT_0_DELAY`, `TC_MIDPOINT` env vars.
- **TemporalCloakClient/Server** (`client.py`, `server.py`) — TCP socket client/server for Demo 1.
- **QuoteProvider** (`quote_provider.py`) — Loads quotes from JSON, provides ASCII-safe random quotes.
- **ImageProvider** (`image_provider.py`) — Provides random image files from `content/images/`.
- **LinkStore** (`link_store.py`) — SQLite-backed storage for shareable links. DB location controlled by `TC_DB_PATH` env var (default: `data/links.db`). Schema has one `links` table with columns: `link_id`, `message`, `image_path`, `image_filename`, `created_at`, `burn_after_reading`, `delivered`.

### Configuration (`config.py` — top-level)

Centralizes all deployment settings via env vars. Key vars: `TC_HOST`, `TC_PORT`, `TC_TLS_CERT`, `TC_TLS_KEY`, `TC_DB_PATH`. Imported by the web demo as `import config`.

### Web Demo (`demos/temporal_cloak_web_demo.py`)

Tornado-based HTTP server with these routes:

| Route | Handler | Purpose |
|-------|---------|---------|
| `GET /api/image` | `ImageHandler` | Random image with random quote encoded in timing |
| `GET /api/health` | `HealthHandler` | Health check (returns uptime) |
| `GET /api/images` | `ImageListHandler` | JSON list of available images |
| `POST /api/create` | `CreateLinkHandler` | Create shareable link (stores message + image in SQLite) |
| `GET /api/link/<id>` | `LinkInfoHandler` | Link metadata (without revealing message) |
| `GET /api/image/<id>` | `EncodedImageHandler` | Image with user's message encoded in timing |
| `GET /api/image/<id>/normal` | `NormalImageHandler` | Image without timing encoding (for thumbnails) |
| `WS /api/decode/<id>` | `DecodeWebSocketHandler` | Real-time decode progress over WebSocket |
| `GET /` | Static | Landing page from `static/` |

The encoding/decoding roles are swapped between demos: in Demo 1 the client encodes and server decodes; in Demo 2 the server encodes and the client decodes.

### Deployment

- **Hosted on:** Hostinger VPS (Ubuntu), runs as systemd service `temporalcloak`
- **Auto-deploy:** `.github/workflows/deploy.yml` — pushes to `main` trigger SSH deploy (git pull + uv sync + restart)
- **TLS:** Tornado handles TLS directly (no nginx) — critical because reverse proxies buffer chunks and destroy timing
- **Service file:** `/etc/systemd/system/temporalcloak.service`
- **Detailed plan:** `docs/deployment-plan.md`

## Commit and PR Guidelines

- Do NOT add `Co-Authored-By` lines to commit messages or PR descriptions.

## Key Implementation Details

- Messages are ASCII-only; `encode_message()` rejects non-ASCII with a `UnicodeEncodeError` check
- `bitstring` library is used for bit-level operations (`BitArray`, `BitStream`, `Bits`)
- Demo 2 uses Tornado's async `flush()` with `time.sleep` via executor for non-blocking delays
- The quotes file (`content/quotes/quotes.json`) is UTF-8 encoded
- All imports use package-qualified paths: `from temporal_cloak.encoding import TemporalCloakEncoding`
