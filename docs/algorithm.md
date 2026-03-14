# TemporalCloak Algorithm

This document describes how TemporalCloak hides secret messages in the timing delays between data transmissions.

## Previous Work

TemporalCloak builds upon decades of research in **covert timing channels** - communication methods that hide information in the timing patterns of legitimate network traffic.

### Foundational Research
- **Lampson, B. W. (1973). A note on the confinement problem. Communications of the ACM, 16(10), 613–615.** Introduced the confinement problem and covert channels, including leakage via effects on shared system resources.
- **Kemmerer, R. A. (1983). Shared resource matrix methodology: An approach to identifying storage and timing channels. ACM Transactions on Computer Systems, 1(3), 256–277.** Presented a systematic methodology for detecting storage and timing channels throughout the software lifecycle.
- **Tsai, C. R., & Gligor, V. D. (1988). A bandwidth computation model for covert storage channels and its applications. Proceedings of the IEEE Symposium on Security and Privacy, 108–121.** Developed a model for computing bandwidth in covert storage channels, with applications to real systems. *(Alternative: Gligor, V. D. (1993). A guide to understanding covert channel analysis of trusted systems (NCSC-TG-030). National Computer Security Center.)*

### Covert Timing Channel Implementations
- **Cabuk, S., Brodley, C. E., & Shields, C. (2004). IP covert timing channels: Design and detection. Proceedings of the 11th ACM Conference on Computer and Communications Security (CCS).** Explored IP covert timing channels and proposed detection methods based on patterns in packet inter-arrival times.
- **Shah, G., Molina, A., & Blaze, M. (2006). Keyboards and covert channels. Proceedings of the 15th USENIX Security Symposium.** Introduced JitterBug mechanisms that create covert network timing channels via timing perturbations at input devices like keyboards.
- **Gianvecchio, S., & Wang, H. (2007). Detecting covert timing channels: An entropy-based approach. Proceedings of the 14th ACM Conference on Computer and Communications Security (CCS).** Proposed entropy-based detection for covert timing channels using information-theoretic measures.
- **Wendzel, S. (various). NetworkCovertChannels: Collection of network covert channel tools.** GitHub repository. https://github.com/cdpxe/NetworkCovertChannels. Aggregates practical implementations including protocol hopping (phcct, 2007), tunneling (vstt, 2006), history-based amplification (DYST, 2025; IEEE TDSC), and reconnection-based wireless channels (2021; IFIP SEC), primarily focusing on storage/hybrid mechanisms, protocol manipulation, and countermeasures.

### Key Insights from Previous Work
Covert timing channels exploit the fact that network protocols inherently include timing variations that are often ignored by security monitoring. Previous research has shown that:
- Timing channels can achieve high bandwidth in certain scenarios through multi-level encoding and parallel channels
- Detection is challenging due to natural network jitter and timing variations
- Most timing channels rely on the covert nature (observer doesn't know to look for timing steganography)
- Detection methods typically use statistical analysis, entropy measures, or machine learning approaches

TemporalCloak advances this field by implementing practical timing steganography with distributed encoding, automatic mode detection, and adaptive threshold calibration.

## Core Concept

TemporalCloak is a **covert timing channel**. The secret message is never present in the transmitted data — it is encoded entirely in the *time gaps* between successive data chunks. The actual bytes sent are irrelevant (random in Client-Encoder, image data in Server-Encoder). Only the inter-arrival timing carries information.

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
│   Boundary   │     Payload       │ Checksum │   Boundary   │
│    0xFF00    │   ASCII message   │  8-bit   │    0xFF00    │
│  (16 bits)   │   (N × 8 bits)    │   XOR    │  (16 bits)   │
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

1. **Validate** the message is ASCII-only (rejects any non-ASCII characters).
2. **Convert** the message string to its bit representation using `bitstring.BitArray`.
3. **Compute** the 8-bit XOR checksum of the raw message bytes.
4. **Assemble** the frame: prepend `0xFF00`, append checksum bits, append `0xFF00`.
5. **Generate delays**: map each bit to its corresponding time delay (`BIT_1_TIME_DELAY` or `BIT_0_TIME_DELAY`).

## Decoding Process (Receiver)

1. **Start timer** on the first received chunk (this chunk carries no timing information).
2. **Mark time** on each subsequent chunk: measure the elapsed time since the previous chunk.
3. **Classify** each delay as `1` (≤ threshold) or `0` (> threshold), appending to a bit stream. Record a confidence score for each bit.
4. **Calibrate** (adaptive threshold): once 16 bits have been received, the decoder uses the first boundary marker (`0xFF00` = 8 ones then 8 zeros) as a calibration preamble. It averages the delays for the `1` group and `0` group, then sets the threshold to their midpoint. All bits are then reclassified with this calibrated threshold.
5. **Search** the accumulated bit stream for boundary markers (exact match first, then fuzzy match allowing up to 2 bit errors).
6. **Extract** the payload between the opening and closing boundaries.
7. **Verify** the checksum (last 8 bits of payload) against the message bytes.
8. **Decode** the remaining bits as text (using `surrogateescape` for non-ASCII byte resilience).
9. **Correct** (if checksum failed): attempt low-confidence bit correction by flipping the least confident bits and re-checking the checksum.

### Confidence Tracking

For each classified bit, the decoder computes a confidence score based on how far the observed delay is from the decision threshold. Bits with confidence below 0.2 are logged as low-confidence, aiding in diagnostics. Confidence scores are also used by the post-decode error correction system (see below).

### Fuzzy Boundary Matching

Network jitter can corrupt not just payload bits but boundary markers themselves. If even one bit of a 16-bit boundary marker is flipped, exact matching fails and the decoder cannot find the message frame.

**The mechanism:** `find_boundary_fuzzy()` scans the bit stream using Hamming distance, accepting any 16-bit window with at most `max_errors` (default 2) bit differences from the expected boundary pattern.

The decoder uses a two-pass strategy:

1. **Start boundary**: Try exact match first, then fuzzy. If the fuzzy match finds a position *earlier* than the exact match, prefer the fuzzy result — the exact match may actually be the intact *end* boundary, while the corrupted *start* boundary was missed.
2. **End boundary**: Try exact match first. If that fails, try fuzzy — but only accept a fuzzy end boundary if the resulting payload is byte-aligned and passes the XOR checksum. This prevents false positives from random bit patterns that happen to resemble a boundary.

The checksum validation on fuzzy end boundaries is critical: a 16-bit pattern with 2-bit tolerance matches roughly 1 in 480 random positions, so without the checksum gate, false matches would be common.

### Low-Confidence Bit Correction

When a message completes but fails checksum validation, the decoder can attempt to recover by flipping the bits it is least confident about. This repurposes the existing checksum as an **error correction oracle** — it can't identify *which* bits are wrong, but it validates whether a correction attempt succeeded.

**The mechanism:** `try_correct_low_confidence_bits()` sorts all bits by confidence score (ascending) and takes the `max_flips` (default 8) least confident as candidates. It then tries:

1. **Single flips** — flip each candidate bit one at a time (up to 8 attempts)
2. **Pair flips** — flip every pair of candidate bits (up to 28 attempts)
3. **Triple flips** — flip every triple of candidate bits (up to 56 attempts)

After each flip, the decoder re-runs `bits_to_message()` and checks the checksum. The first combination that produces a valid checksum wins. If no combination works, the original bits are restored.

**Why this works:** Network jitter typically corrupts bits near the decision threshold — exactly the bits with low confidence scores. By targeting those bits first, the search space is small enough for brute-force (92 total attempts for 8 candidates) while covering the most likely error patterns. The 8-bit XOR checksum has a 1/256 false positive rate per attempt, making accidental matches unlikely across 92 trials.

**Limitations:** The approach can correct at most 3 bit errors in the message payload. Beyond that, the combinatorial explosion makes brute-force impractical, and the checksum's false positive rate becomes a concern. For higher error rates, forward error correction (e.g., Hamming codes) would be needed.

### Carry-Forward Delay Compensation

**The problem:** Network jitter and TCP buffering can shift delay from one gap to the next. When one gap runs long, it effectively steals time from its neighbor — the total time across the two gaps is roughly conserved, but it lands on the wrong gap. This causes the oversized gap to be misclassified and can cascade into multiple flipped bits.

**Example from production data:**

In every observed case, the pattern is the same: an oversized delay on one gap is followed by an undersized delay on the next. The total time across the two gaps is roughly conserved, but it lands on the wrong gap.

The server intended two consecutive `0` bits — delays of `[300ms, 300ms]`. What the client observed:

```
Gap A: Expected 0 (300ms) → Observed 490ms  ✓ (above midpoint, correct — but oversized)
Gap B: Expected 0 (300ms) → Observed 110ms  ✗ (below midpoint, decoded as 1 — WRONG)
```

Gap A absorbed ~190ms of extra delay, stealing it from gap B. The 110ms observed at gap B falls below the midpoint (175ms) and is misclassified as `1`.

**The mechanism:** The decoder knows the maximum intentional delay (`BIT_0_TIME_DELAY × max_delay_margin`). When a corrected delay exceeds this cap, the excess is carried forward and added to the next gap's measurement before classification. The cap is only used for carry-forward decisions — bit classification still uses the midpoint threshold.

**Carry cap:** Carry is clamped to `threshold × max_carry_fraction` (default 0.5) after each overflow. Without this cap, a single very large delay (e.g., 500ms when expecting 300ms) can accumulate enough carry to flip the *next* clean bit. For example, a 500ms gap produces 170ms of carry — enough to push a clean 1ms `1`-bit above the 175ms midpoint, misclassifying it as `0`. The cap limits carry to ~78ms (175ms × 0.5), which is too small to flip a clean bit but still enough to correct a shifted neighbor.

```python
max_expected = server_config.bit_0_delay * 1.1   # 330ms with 10% margin
max_carry = threshold * 0.5                       # carry cap
carry = 0.0

for each raw_delay in gaps:
    corrected = raw_delay + carry
    if corrected > max_expected:
        carry = min(corrected - max_expected, max_carry)  # clamp carry
        corrected = max_expected
    else:
        carry = 0.0
    classify_bit(corrected)              # uses midpoint threshold, not max_expected
```

**Walkthrough** (midpoint = 0.175s, max_expected = 0.330s):

```
Gap A: raw=0.490 + carry=0.000 = 0.490  → exceeds max_expected (0.330), cap it
       corrected=0.330, carry=0.160
       classify: 0.330 > 0.175 midpoint → bit 0 ✓

Gap B: raw=0.110 + carry=0.160 = 0.270  → below max_expected, no new carry
       carry=0.000
       classify: 0.270 > 0.175 midpoint → bit 0 ✓  (was bit 1 without compensation)
```

Without carry-forward, gap B (110ms) falls below the 175ms midpoint and decodes as `1`. With carry-forward, the 160ms excess from gap A is added to gap B, bringing it to 270ms — correctly above the midpoint.

**The effect:** In production, this pattern was observed at multiple points in a single transmission. Carry-forward corrects the undersized neighbor in each case, reducing bit errors per incident.

**The limitation:** Carry-forward fixes the *receiving* gap (where excess delay accumulated) and can redistribute surplus to the next gap. But it cannot fix the *originating* gap (where delay was stolen from), because at that point the carry is still zero — we don't know delay was stolen until we see the oversized gap that follows.

**In distributed mode**, carry is reset on filler gaps (gaps that don't carry message bits). This prevents stale carry values from leaking across non-adjacent message bits, since scattered bit positions may be separated by many filler gaps.

**Configuration:** Carry-forward is controlled by three parameters on all decoder classes:
- `carry_forward` (default: `True`) — enables or disables compensation
- `max_delay_margin` (default: `1.1`) — multiplier on `BIT_0_TIME_DELAY` to set the cap
- `max_carry_fraction` (default: `0.5`) — maximum carry as a fraction of threshold, prevents oversized delays from flipping subsequent clean bits

## Encoding Modes

TemporalCloak supports two encoding modes that control how message bits are placed across chunk gaps:

### Frontloaded Mode

All message bits are packed contiguously into the first N chunk gaps. Simple and efficient, but creates a detectable pattern: early chunks have variable delays while later chunks arrive at uniform speed.

**Boundary marker**: `0xFF00`

**Frame format**: same as described above — boundary + payload + checksum + boundary, all contiguous.

### Distributed Mode

Message bits are **scattered pseudo-randomly** across all available chunk gaps, making the timing pattern much harder to distinguish from natural network jitter. Only the preamble is contiguous; the remaining bits are placed at positions selected by a PRNG seeded with a random key.

**Boundary marker**: `0xFF01` (differs in the last bit so the decoder can auto-detect the mode)

**Preamble** (32 bits, contiguous at positions 0–31):

```
┌──────────────┬──────────┬─────────────┐
│   Boundary   │   Key    │  Msg Length │
│    0xFF01    │  8-bit   │   8-bit     │
│  (16 bits)   │  random  │  (chars)    │
└──────────────┴──────────┴─────────────┘
```

**Scattered data** (placed at PRNG-selected positions after the preamble):
Message payload + checksum + **ending boundary** (all scattered randomly)

```
┌───────────────────┬──────────┬──────────────┐
│     Payload       │ Checksum │ Ending       │
│   ASCII message   │  8-bit   │ Boundary     │
│   (N × 8 bits)    │   XOR    │ (16 bits)    │
│                   │          │   0xFF01     │
└───────────────────┴──────────┴──────────────┘
```

*Note: Distributed mode includes an ending boundary marker just like frontloaded mode, even though the preamble contains the message length. This provides additional error detection and maintains frame format consistency. The length field specifies character count, while boundary markers provide the actual message framing in the bit stream.*

**Bit position selection**:

The encoder needs to decide *which* of the many chunk gaps after the preamble will carry real message bits. It does this deterministically using the random key so that the decoder can reconstruct the same positions without any extra signalling.

The image file size directly controls how many gaps are available for scattering. The image is split into fixed-size chunks (default 256 bytes), and each pair of consecutive chunks creates one gap:

```
total_gaps = ⌈image_size / chunk_size⌉ - 1
```

The receiver knows `total_gaps` before decoding begins because the server includes the standard HTTP `Content-Length` header in the response. Since the chunk size is a shared constant (`CHUNK_SIZE_TORNADO = 256`), both sides compute identical `total_gaps` values from the same formula. The `Content-Length` header is a normal part of any HTTP response, so it reveals nothing about the hidden message.

A larger image means more gaps, which means more candidate positions to scatter bits across. This has two effects:

- **Better stealth**: with more filler gaps between message bits, the timing pattern becomes sparser and harder to detect. A 100 KB image (~390 gaps) hiding a 5-char message uses only ~64 of 358 candidate positions (~18%), while a 500 KB image (~1953 gaps) uses the same 64 bits across 1921 candidates (~3%).
- **Same capacity ceiling**: the maximum message length is capped at 255 characters regardless of image size, since the length field is only 8 bits. A bigger image doesn't let you encode longer messages — it just hides them better.

If the image is too small to provide enough gaps for the message plus overhead, the encoder rejects it (validated by `DistributedEncoder.validate_image_size()`).

**Step 1 — List available positions.** Every gap index from 32 (end of preamble) to `total_gaps - 1` is a candidate. For example, an image that produces 200 chunk gaps has candidate positions `[32, 33, 34, ..., 199]` — that's 168 candidates.

**Step 2 — Shuffle with the key.** The key seeds a PRNG (`random.Random(key)`), which shuffles the candidate list into a pseudo-random order. A different key produces a completely different ordering.

**Step 3 — Take the first M.** The encoder needs M positions, where M = `msg_len × 8 + 8 (checksum) + 16 (end boundary)`. It takes the first M values from the shuffled list.

**Step 4 — Sort ascending.** The selected positions are sorted so bits are placed in order as the transmission progresses. This means the encoder and decoder can process chunks in a single forward pass.

The preamble (32 bits) is always contiguous at positions 0–31. Only the remaining message, checksum, and end-boundary bits are scattered across positions 32+.

Here's a concrete example encoding a 2-character message (`"Hi"`) into an image with 80 chunk gaps:

```
Total encoded bits: 32 preamble (contiguous) + 40 scattered = 72

M = 2×8 + 8 + 16 = 40 bits to scatter (after the preamble)
    │ │   │   │
    │ │   │   └── end boundary (0xFF01 terminator, 16 bits)
    │ │   └────── checksum (1 byte for integrity check)
    │ └────────── 8 bits per ASCII character
    └──────────── 2 characters in "Hi"

Candidates: [32, 33, 34, 35, 36, 37, ... 79]   (48 positions)

Shuffle with key=42:
  [58, 35, 71, 44, 33, 67, 39, 76, 52, 46, ...]

Take first 40, then sort:
  [33, 35, 37, 39, 41, 44, 46, 48, 50, 52, ... 76, 78]
```

The resulting gap layout looks like this:

```mermaid
graph LR
    A[Boundary<br/>16 bits<br/>0xFF01] --> B[Key<br/>8 bits<br/>random] --> C[Length<br/>8 bits<br/>char count]

    C --> D[Message<br/>N×8 bits<br/>ASCII payload] --> E[Checksum<br/>8 bits<br/>XOR] --> F[End Boundary<br/>16 bits<br/>0xFF01]

    A:::boundary
    B:::metadata
    C:::metadata
    D:::payload
    E:::metadata
    F:::boundary

    classDef boundary fill:#e8f5e8,stroke:#2e7d32
    classDef metadata fill:#e1f5fe,stroke:#01579b
    classDef payload fill:#fff3e0,stroke:#ef6c00
```

**Layout**: Positions 0-31 are contiguous preamble, positions 32+ are scattered data at PRNG-selected locations.

**Example**: For "Hi" (2 chars) with 80 gaps:
- **Contiguous preamble**: Positions 0-31 (32 bits total)
- **Scattered data**: 40 bits (16 message + 8 checksum + 16 end boundary) at PRNG-selected positions 32-79
- **Filler gaps**: Remaining positions use zero delay (indistinguishable from '1' bits)

Because the key is only 8 bits, both encoder and decoder share a small search space (256 possible shuffles). But the key isn't meant for cryptographic secrecy — it just spreads the bits out. The security of the covert channel rests on the observer not knowing that timing steganography is being used at all.

**Filler gaps**: all gaps that don't carry a real bit use zero added delay. With the default localhost settings (where `BIT_1_DELAY` is also zero), filler is indistinguishable from a `1` bit on the wire. On internet deployments where `BIT_1_DELAY` is non-zero, filler gaps are slightly faster than real `1` bits, but both are still much shorter than `0` bits. This means an observer sees short delays scattered throughout the entire transmission rather than clustered at the start.

**Maximum message length**: capped at 255 characters (the 8-bit length field in the preamble).

### Auto-Detection

The decoder (`AutoDecoder`) collects the first 16 timing delays (the boundary marker), calibrates a threshold, and checks the last bit:

- Bit 15 = `0` → boundary is `0xFF00` → **frontloaded mode**
- Bit 15 = `1` → boundary is `0xFF01` → **distributed mode**

It then instantiates the appropriate decoder and replays the collected delays.

## Transmission Modes

### Client-Encoder: Raw TCP Sockets

The client sends **one random byte per bit**, with the delay between sends encoding the message. The server receives bytes one at a time and measures inter-arrival times. Uses frontloaded encoding. The server uses `StreamingFrontloadedDecoder`, a subclass that truncates the bit buffer after each completed message to support multiple messages on the same TCP connection.

```mermaid
sequenceDiagram
    participant Client
    participant Server

    Note over Client,Server: Client-Encoder - Raw TCP Sockets (Frontloaded)

    Client->>Server: Random byte (sync, discarded)
    Note right of Server: start_timer()

    Client->>Server: Random byte + sleep(delay[0])
    Note right of Server: mark_time() → bit 0

    Client->>Server: Random byte + sleep(delay[1])
    Note right of Server: mark_time() → bit 1

    Note over Client: ...continue for each bit...
```

### Server-Encoder: HTTP Chunked Image Transfer

The server sends an image file in fixed-size chunks (default 256 bytes) over HTTP. The delay between chunks encodes a hidden quote. The client fetches the image and decodes timing from chunk arrivals. Uses distributed encoding by default.

```mermaid
sequenceDiagram
    participant Server
    participant Client

    Note over Server,Client: Server-Encoder - HTTP Image Transfer (Distributed)

    Server->>Client: Image chunk[0]
    Note right of Client: start_timer()

    Server->>Client: sleep(delay[0]) + Image chunk[1]
    Note right of Client: mark_time() → bit 0

    Server->>Client: sleep(delay[1]) + Image chunk[2]
    Note right of Client: mark_time() → bit 1

    Note over Server,Client: ...continue for each chunk...
    Note right of Client: Most gaps have zero delay (filler)
```

In distributed mode, most chunk gaps carry zero delay (filler). Only the preamble gaps and the PRNG-selected gaps carry real timing information. The client's `AutoDecoder` detects the mode from the boundary marker and knows which gaps to interpret.

The encoding/decoding roles are **swapped** between modes: in Client-Encoder the client encodes; in Server-Encoder the server encodes.

## Capacity

The number of characters a transmission can carry depends on the available "delay slots":

- **Client-Encoder (TCP)**: unlimited — the client can send as many bytes as needed.
- **Server-Encoder (HTTP image)**: constrained by image file size. Each chunk after the first provides one delay slot.

**Frontloaded mode** — maximum message length for an image of size `S` bytes with chunk size `C`:

```
max_chars = (⌈S/C⌉ - 1 - 40) / 8
```

where 40 accounts for the two 16-bit boundaries and the 8-bit checksum.

**Distributed mode** — same formula but with additional overhead for the key and length fields:

```
max_chars = (⌈S/C⌉ - 1 - 56) / 8
```

where 56 = two 16-bit boundaries + 8-bit checksum + 8-bit key + 8-bit length. Also hard-capped at 255 characters.

## Throughput

Throughput depends on two factors per bit: the encoding delay (`D`) and the baseline chunk transfer time (`T`). The actual time per bit is `T + D`, where:

- `T` = time to transfer one chunk (network-dependent, independent of encoding)
- `D` = added delay for encoding (`0.00s` for a `1` bit, `0.10s` for a `0` bit with defaults)

| Environment | `T` (approx) | Notes |
|-------------|--------------|-------|
| localhost   | ~0.001s      | Negligible compared to `D` |
| Production  | ~0.02s       | Hostinger VPS, varies with client distance |

With default delay values:

- **Best case** (all 1s): `T` per bit (~0.001s localhost, ~0.02s production)
- **Worst case** (all 0s): `T + 0.10s` per bit ≈ 1.25 bytes/second
- **Average** (50/50 mix): `T + ~0.05s` per bit ≈ 2.5 bytes/second

This is intentionally slow — covert channels trade bandwidth for stealth.

In distributed mode, the total transmission time is dominated by the image transfer itself, since most gaps are zero-delay filler. The message bits are spread across the full duration rather than concentrated at the start, trading slightly more total time for significantly better stealth.

## Hamming(12,8) Forward Error Correction

TemporalCloak supports optional Hamming(12,8) forward error correction (FEC), which encodes redundancy directly into the transmitted bits. When enabled, the decoder can automatically correct single-bit errors per byte *before* the checksum is checked — complementing the existing post-decode error correction.

### Scheme

Each 8-bit data byte is encoded into a 12-bit Hamming codeword by inserting 4 parity bits at positions that are powers of 2:

```
Position (1-indexed):  1   2   3   4   5   6   7   8   9  10  11  12
Bit:                  p1  p2  d1  p4  d2  d3  d4  p8  d5  d6  d7  d8
```

Each parity bit covers positions whose binary index has that power-of-2 bit set:
- p1 (pos 1): covers positions 1, 3, 5, 7, 9, 11
- p2 (pos 2): covers positions 2, 3, 6, 7, 10, 11
- p4 (pos 4): covers positions 4, 5, 6, 7, 12
- p8 (pos 8): covers positions 8, 9, 10, 11, 12

On decode, the decoder computes a 4-bit syndrome from the parity checks. A zero syndrome means no errors. A nonzero syndrome identifies the exact position of a single-bit error, which is then flipped to recover the original data.

### Wire Format Signaling

The boundary marker's last 2 bits encode both encoding mode and FEC:

| Boundary | Bit 15 (mode) | Bit 14 (FEC) | Meaning |
|----------|---------------|--------------|---------|
| `0xFF00` | 0 | 0 | Frontloaded, no FEC |
| `0xFF01` | 1 | 0 | Distributed, no FEC |
| `0xFF02` | 0 | 1 | Frontloaded + Hamming |
| `0xFF03` | 1 | 1 | Distributed + Hamming |

This is backward compatible: old decoders searching for `0xFF00`/`0xFF01` won't match the FEC variants.

### Frame Format with Hamming

```
┌──────────────┬───────────────────┬────────────────────────────────┬──────────────┐
│   Boundary   │    Preamble*      │      Hamming Payload           │   Boundary   │
│  0xFF02/03   │  (distributed     │  (message + checksum)          │  0xFF02/03   │
│  (16 bits)   │   only: key+len)  │  N × 12 bits                   │  (16 bits)   │
└──────────────┴───────────────────┴────────────────────────────────┴──────────────┘
```

- Boundaries are **not** Hamming-encoded — they serve as calibration patterns
- The checksum is computed on raw message bytes, then the combined `message_bytes + checksum_byte` are Hamming-encoded together as a sequence of 12-bit blocks
- After Hamming decoding, the standard checksum verification still runs as a second validation layer
- Overhead: 50% more bits per character (8→12 bits per byte)

### Interaction with Existing Error Correction

Hamming FEC and the existing error correction layers stack without interference:

1. **Hamming (per-block)**: Corrects single-bit errors within each 12-bit block automatically during decode. This happens *before* checksum verification.
2. **Checksum verification**: After Hamming decode, the XOR checksum validates the entire message. If Hamming miscorrected a 2-bit error (producing a wrong byte), the checksum catches it.
3. **Low-confidence bit correction**: If the checksum still fails, the existing brute-force correction runs on the raw timing-derived bits and re-calls `bits_to_message()`, which internally does Hamming decode again. This catches errors that Hamming missed (e.g., 2+ bit errors in a single block).

### Auto-Detection

The `AutoDecoder` detects FEC from the boundary marker during bootstrap. After collecting 16 timing delays, it examines:
- Bit 15 (last bit): encoding mode (0=frontloaded, 1=distributed)
- Bit 14 (second-to-last): FEC (0=none, 1=Hamming)

No decoder-side flag is needed — FEC is fully auto-detected from the wire format.

### Capacity Impact

Hamming increases the per-byte cost from 8 to 12 bits (50% overhead). For the same image, the maximum message length is reduced:

| Image Size | Max chars (no FEC) | Max chars (Hamming) |
|------------|-------------------|---------------------|
| 50 KB      | ~24 (frontloaded) | ~15 (frontloaded)   |
| 100 KB     | ~48 (frontloaded) | ~31 (frontloaded)   |
| 500 KB     | ~244 (frontloaded)| ~162 (frontloaded)  |

The distributed mode 255-character limit (8-bit preamble length field) still applies.

## Future Work

Several advanced techniques could enhance TemporalCloak's bandwidth and robustness:

### Multi-Image Timing Differential
Instead of encoding within a single image's chunk gaps, future work could measure timing differences between corresponding chunks of two different images. This approach would:
- Encode information in the relative timing between parallel streams
- Provide higher bandwidth through cross-stream timing relationships
- Add another layer of steganographic concealment

### Advanced Modulation Techniques
- **Multi-level encoding**: Use more than two delay values (e.g., 4 or 8 delay levels) to encode multiple bits per timing event, significantly increasing bandwidth
- **Frequency domain modulation**: Encode information in the frequency spectrum of timing patterns rather than just delay durations. Instead of binary delay lengths, create timing sequences with different frequency characteristics (e.g., high-frequency rapid delays vs. low-frequency spaced delays) that can be detected through spectral analysis. This allows encoding information in both the timing and frequency domains for higher bandwidth.
- **Phase modulation**: Vary the relative timing phase between different packet streams
- **Adaptive modulation**: Dynamically adjust encoding parameters based on detected network conditions and jitter patterns
- **Forward error correction**: Hamming(12,8) FEC is now implemented as an optional feature (see above). Future work could add stronger codes like Reed-Solomon for correcting multi-bit burst errors at the cost of higher overhead

## Conclusion

TemporalCloak demonstrates a practical implementation of covert timing channel steganography, hiding secret messages entirely within the timing patterns of legitimate HTTP image transfers and TCP socket communications.

### Key Innovation
TemporalCloak is best understood as a practical, production-style example of covert timing channel steganography: one of the few publicly available, user-friendly implementations that supports dual real-world modes (client TCP and server HTTP image transfer). Its distinguishing features include:
- **Real-world deployment**: Running as a systemd service on a public VPS with TLS termination
- **Dual transmission modes**: Supporting both client-initiated (TCP sockets) and server-initiated (HTTP image transfers) covert communication
- **Automatic mode detection**: Self-identifying encoding schemes through boundary marker analysis
- **Robust error handling**: Adaptive threshold calibration, carry-forward delay compensation with carry cap, fuzzy boundary matching, confidence-based bit correction, and checksum validation for reliable operation over lossy networks

### Contributions to the Field
TemporalCloak advances covert timing channel research by providing a complete, deployable system that addresses practical challenges in real-world network environments. It demonstrates how timing steganography can achieve reliable communication while maintaining the covert nature that makes these channels difficult to detect.

### Applications and Limitations
Covert timing channels like TemporalCloak have applications in secure communications where traditional encryption might attract attention. However, they are inherently low-bandwidth and rely on the observer's ignorance of timing steganography for security. Future work in advanced modulation techniques could significantly improve bandwidth while maintaining stealth properties.
