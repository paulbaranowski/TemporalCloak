# TemporalCloak Algorithm

This document describes how TemporalCloak hides secret messages in the timing delays between data transmissions.

## Core Concept

TemporalCloak is a **covert timing channel**. The secret message is never present in the transmitted data — it is encoded entirely in the *time gaps* between successive data chunks. The actual bytes sent are irrelevant (random in Demo 1, image data in Demo 2). Only the inter-arrival timing carries information.

## Bit Encoding

Each bit of the secret message maps to a time delay:

| Bit | Delay (localhost) | Delay (internet) |
|-----|-------------------|-------------------|
| `1` | 0.00s             | 0.05s             |
| `0` | 0.10s             | 0.30s             |

The receiver classifies each observed delay using a **midpoint threshold** (default 0.05s on localhost, 0.175s over the internet). Delays at or below the threshold are read as `1`; delays above it are read as `0`.

All timing parameters are configurable via environment variables (`TC_BIT_1_DELAY`, `TC_BIT_0_DELAY`, `TC_MIDPOINT`).

## Frame Format

A complete message transmission has this bit-level layout:

```
┌──────────────┬───────────────────┬──────────┬──────────────┐
│  Boundary    │  Payload          │ Checksum │  Boundary    │
│  0xFF00      │  ASCII message    │  8-bit   │  0xFF00      │
│  (16 bits)   │  (N × 8 bits)     │  XOR     │  (16 bits)   │
└──────────────┴───────────────────┴──────────┴──────────────┘
```

**Total bits** = 16 (boundary) + N×8 (message) + 8 (checksum) + 16 (boundary) = N×8 + 40

### Boundary Marker (0xFF00)

The boundary marker is `0xFF00` — 8 ones followed by 8 zeros. It serves two purposes:

1. **Message framing**: marks the start and end of each message so the receiver knows where payload bits begin and end.
2. **Collision safety**: since messages are restricted to ASCII (all bytes < `0x80`), the byte `0xFF` can never appear in the payload, guaranteeing the boundary pattern is unambiguous.

### Checksum

An 8-bit XOR checksum is computed over the raw payload bytes and appended after the message bits. The receiver verifies this checksum after finding the closing boundary. A mismatch triggers a warning that the message may be corrupted.

## Encoding Process (Sender)

1. **Validate** the message is ASCII-only (rejects any byte ≥ `0x80`).
2. **Convert** the message string to its bit representation using `bitstring.BitArray`.
3. **Compute** the 8-bit XOR checksum of the raw message bytes.
4. **Assemble** the frame: prepend `0xFF00`, append checksum bits, append `0xFF00`.
5. **Generate delays**: map each bit to its corresponding time delay (`BIT_1_TIME_DELAY` or `BIT_0_TIME_DELAY`).

## Decoding Process (Receiver)

1. **Start timer** on the first received chunk (this chunk carries no timing information).
2. **Mark time** on each subsequent chunk: measure the elapsed time since the previous chunk.
3. **Classify** each delay as `1` (≤ threshold) or `0` (> threshold), appending to a bit stream.
4. **Calibrate** (adaptive threshold): once 16 bits have been received, the decoder uses the first boundary marker (`0xFF00` = 8 ones then 8 zeros) as a calibration preamble. It averages the delays for the `1` group and `0` group, then sets the threshold to their midpoint. All bits are then reclassified with this calibrated threshold.
5. **Search** the accumulated bit stream for boundary markers.
6. **Extract** the payload between the opening and closing boundaries.
7. **Verify** the checksum (last 8 bits of payload) against the message bytes.
8. **Decode** the remaining bits as ASCII text.

### Confidence Tracking

For each classified bit, the decoder computes a confidence score based on how far the observed delay is from the decision threshold. Bits with confidence below 0.2 are logged as low-confidence, aiding in diagnostics.

## Transmission Modes

### Demo 1: Raw TCP Sockets

The client sends **one random byte per bit**, with the delay between sends encoding the message. The server receives bytes one at a time and measures inter-arrival times.

```
Client                          Server
  │                               │
  ├─── random byte ───────────────►│  (sync byte, discarded)
  │     sleep(delay[0])           │
  ├─── random byte ───────────────►│  mark_time() → bit 0
  │     sleep(delay[1])           │
  ├─── random byte ───────────────►│  mark_time() → bit 1
  │     ...                       │  ...
```

### Demo 2: HTTP Chunked Image Transfer

The server sends an image file in fixed-size chunks (default 256 bytes) over HTTP. The delay between chunks encodes a hidden quote. The client fetches the image and decodes timing from chunk arrivals.

```
Server                          Client
  │                               │
  ├─── image chunk[0] ───────────►│  start_timer()
  │     sleep(delay[0])           │
  ├─── image chunk[1] ───────────►│  mark_time() → bit 0
  │     sleep(delay[1])           │
  ├─── image chunk[2] ───────────►│  mark_time() → bit 1
  │     ...                       │  ...
```

The encoding/decoding roles are **swapped** between demos: in Demo 1 the client encodes; in Demo 2 the server encodes.

## Capacity

The number of characters a transmission can carry depends on the available "delay slots":

- **Demo 1 (TCP)**: unlimited — the client can send as many bytes as needed.
- **Demo 2 (HTTP image)**: constrained by image file size. Each chunk after the first provides one delay slot. The maximum message length for an image of size `S` bytes with chunk size `C` is:

```
max_chars = (⌈S/C⌉ - 1 - 40) / 8
```

where 40 accounts for the two 16-bit boundaries and the 8-bit checksum.

## Throughput

Throughput depends on the delay values. On localhost with defaults (0.00s for `1`, 0.10s for `0`):

- **Best case** (all 1s): effectively instant
- **Worst case** (all 0s): 0.10s per bit = 1.25 bytes/second
- **Average** (50/50 mix): ~0.05s per bit = 2.5 bytes/second

This is intentionally slow — covert channels trade bandwidth for stealth.
