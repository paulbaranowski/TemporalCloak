# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TemporalCloak is a time-based steganography tool. It hides secret messages in the **timing delays** between data transmissions — not in the data content itself. Messages are encoded as bit sequences where each bit maps to a specific time delay (short delay = 1, longer delay = 0). A boundary marker (`0xFF00`) frames each message.

## Commands

```bash
# Setup (uses uv)
uv sync

# Tests (unittest, no pytest)
uv run python -m unittest discover -s tests -v

# Demo 1: Client sends hidden message to server via raw TCP sockets
uv run python demos/demo1_server.py   # start first, listens on localhost:1234
uv run python demos/demo1_client.py   # prompts for message, sends with timing encoding

# Demo 2: Server embeds hidden quote in HTTP image response (Tornado)
uv run python demos/demo2_server_tornado.py   # starts on localhost:8888, serves images
uv run python demos/demo2_client_tornado.py   # fetches image, decodes hidden quote from chunk timing
```

## Project Structure

```
temporal_cloak/          # Main package
├── __init__.py          # Re-exports all public classes
├── const.py             # Protocol constants (delays, boundary marker, chunk size)
├── encoding.py          # Message → bit array → delay sequence
├── decoding.py          # Timing → bits → message reconstruction
├── client.py            # TCP socket client for sending encoded messages
├── server.py            # TCP socket server for receiving/decoding messages
├── quote_provider.py    # Random ASCII-safe quote selection
└── image_provider.py    # Random image file selection
demos/                   # Runnable demo scripts
├── demo1_client.py
├── demo1_server.py
├── demo2_server_tornado.py
└── demo2_client_tornado.py
tests/                   # Per-module test files
├── test_decoding.py
├── test_encoding.py
├── test_quote_provider.py
├── test_image_provider.py
├── test_client.py
├── test_server.py
└── test_integration.py
content/                 # Static assets
├── images/
└── quotes/quotes.json
```

## Architecture

The `temporal_cloak` package contains the core modules:

- **TemporalCloakConst** (`const.py`) — Protocol constants: bit delays, midpoint threshold, boundary marker, chunk size
- **TemporalCloakEncoding** (`encoding.py`) — Converts a string message → bit array → delay sequence. Prepends boundary bits. Used by senders (demo1 client, demo2 server)
- **TemporalCloakDecoding** (`decoding.py`) — Reconstructs messages from timing: accumulates bits via `mark_time()`, finds boundary markers, decodes bit stream back to text. Used by receivers (demo1 server, demo2 client)
- **TemporalCloakClient** (`client.py`) — TCP socket client that sends bytes with timing-encoded delays
- **TemporalCloakServer** (`server.py`) — TCP socket server that receives bytes and decodes timing
- **QuoteProvider** (`quote_provider.py`) — Loads quotes from JSON, provides ASCII-safe random quotes
- **ImageProvider** (`image_provider.py`) — Provides random image files from the content directory

The encoding/decoding roles are swapped between demos: in Demo 1 the client encodes and server decodes; in Demo 2 the server encodes (hiding a quote in image chunk timing) and the client decodes.

## Key Implementation Details

- Messages are ASCII-only; `encode_message()` rejects non-ASCII with a `UnicodeEncodeError` check
- `bitstring` library is used throughout for bit-level operations (`BitArray`, `BitStream`, `Bits`)
- Demo 2 uses Tornado's async `flush()` with `time.sleep` via executor for non-blocking delays
- The quotes source file (`content/quotes/quotes.json`) uses `Windows-1252` encoding
- All imports use package-qualified paths: `from temporal_cloak.encoding import TemporalCloakEncoding`
