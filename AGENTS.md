# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

TemporalCloak is a time-based steganography proof-of-concept. It hides secret messages in the **time delays between data transmissions** rather than in the data itself. A sender encodes a message as a sequence of short/long pauses between bytes or chunks; a receiver measures those pauses to reconstruct the hidden message.

## Setup

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Dependencies: `bitstring`, `tornado`, `requests`, `rich`, `humanize`.

## Running Tests

```
python test.py
```

Tests use the `unittest` stdlib module. There is a single test file (`test.py`) covering `TemporalCloakDecoding` and boundary-finding logic.

## Running the Demos

**Demo 1** (raw TCP socket, client→server): start `python demo1_server.py`, then `python demo1_client.py`.

**Demo 2** (Tornado HTTP, server→client): start `python temporal_cloak_web_demo.py`, then `python temporal_cloak_cli_decoder.py`. The server also serves images at http://localhost:8888.

## Architecture

### Core library (3 files)

- **`TemporalCloakConst.py`** — Shared constants: bit delay values (`BIT_1_TIME_DELAY`, `BIT_0_TIME_DELAY`), the midpoint threshold for classifying received bits, the boundary marker (`0xFF00`) used to frame messages, and the chunk size for Tornado streaming.
- **`TemporalCloakEncoding.py`** — Encoder. Converts an ASCII string into a `BitArray`, prepends the boundary marker, and generates a list of time delays (one per bit). Consumers call `cloak.message = "text"` (setter triggers encoding + delay generation), then iterate over `cloak.delays`.
- **`TemporalCloakDecoding.py`** — Decoder. Accumulates bits by measuring inter-arrival times (`mark_time()`), classifies each as 0 or 1 using `MIDPOINT_TIME`, and searches the growing bitstream for boundary markers to extract complete messages. Supports continuous streaming — once a message is found, `jump_to_next_message()` truncates consumed bits so the next message can be decoded.

### Encoding/decoding flow

1. Encoder ASCII-encodes the message, converts to bits, prepends `BOUNDARY_BITS`.
2. Each bit maps to a delay: `BIT_1_TIME_DELAY` (0.00s) for 1, `BIT_0_TIME_DELAY` (0.05s) for 0.
3. Sender transmits arbitrary data with these delays between sends.
4. Decoder calls `start_timer()` on the first chunk, then `mark_time()` on each subsequent chunk.
5. `mark_time()` measures the inter-arrival gap, classifies it as 0/1, appends to a `BitStream`, and calls `bits_to_message()` which scans for two boundary markers to extract the payload between them.

### Demo structure

- **Demo 1**: Direct TCP. Client encodes a user-supplied message and sends random bytes with encoded delays in a loop. Server receives one byte at a time and decodes.
- **Demo 2**: HTTP/Tornado. Server picks a random quote from `content/quotes/quotes.json`, encodes it as delays between image chunks. Client streams the response and decodes. The image is served from `content/images/`.

### Static content

`content/images/` — JPEG images served by Demo 2.
`content/quotes/quotes.json` — JSON array of `{quoteText, quoteAuthor}` objects (Windows-1252 encoded).
