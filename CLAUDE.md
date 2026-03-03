# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TemporalCloak is a time-based steganography tool. It hides secret messages in the **timing delays** between data transmissions — not in the data content itself. Messages are encoded as bit sequences where each bit maps to a specific time delay (short delay = 1, longer delay = 0). A boundary marker (`0xFF00`) frames each message.

## Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Tests (unittest, no pytest)
python test.py

# Demo 1: Client sends hidden message to server via raw TCP sockets
python demo1_server.py   # start first, listens on localhost:1234
python demo1_client.py   # prompts for message, sends with timing encoding

# Demo 2: Server embeds hidden quote in HTTP image response (Tornado)
python demo2_server_tornado.py   # starts on localhost:8888, serves images
python demo2_client_tornado.py   # fetches image, decodes hidden quote from chunk timing
```

## Architecture

Three core modules with no package structure (all top-level `.py` files):

- **TemporalCloakConst** — Protocol constants: bit delays, midpoint threshold, boundary marker, chunk size
- **TemporalCloakEncoding** — Converts a string message → bit array → delay sequence. Prepends boundary bits. Used by senders (demo1 client, demo2 server)
- **TemporalCloakDecoding** — Reconstructs messages from timing: accumulates bits via `mark_time()`, finds boundary markers, decodes bit stream back to text. Used by receivers (demo1 server, demo2 client)

The encoding/decoding roles are swapped between demos: in Demo 1 the client encodes and server decodes; in Demo 2 the server encodes (hiding a quote in image chunk timing) and the client decodes.

## Key Implementation Details

- Messages are ASCII-only; `encode_message()` rejects non-ASCII with a `UnicodeEncodeError` check
- `bitstring` library is used throughout for bit-level operations (`BitArray`, `BitStream`, `Bits`)
- Demo 2 uses Tornado's async `flush()` with `time.sleep` via executor for non-blocking delays
- The quotes source file (`content/quotes/quotes.json`) uses `Windows-1252` encoding
