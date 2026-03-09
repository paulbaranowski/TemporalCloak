import json
import math
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

import click
import requests
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text

from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.decoding import AutoDecoder

DEFAULT_URL = "https://temporalcloak.cloud/api/image"


def _extract_link_id(url):
    """Extract the link ID from a view URL, API URL, or bare ID.

    Accepts:
      - https://host/view.html?id=abc123
      - https://host/api/image/abc123
      - https://host/api/image/abc123/debug
      - https://host/api/image/abc123/normal
      - abc123  (bare ID)

    Returns None for URLs without a link ID (e.g. /api/image with no ID).
    """
    parsed = urlparse(url)

    # Bare ID (no scheme)
    if not parsed.scheme:
        return url.strip()

    # view.html?id=...
    if parsed.path.rstrip("/").endswith("view.html"):
        link_id = parse_qs(parsed.query).get("id", [None])[0]
        if not link_id:
            Console().print("[bold red]Error:[/bold red] URL is missing the ?id= parameter.")
            sys.exit(1)
        return link_id

    # /api/image/<id>[/suffix]
    parts = parsed.path.rstrip("/").split("/")
    # With suffix: /api/image/<id>/debug → parts[-2] is the ID
    if len(parts) >= 4 and parts[-3] == "image" and parts[-1] in ("debug", "normal"):
        return parts[-2]
    # Without suffix: /api/image/<id> → parts[-1] is the ID
    if len(parts) >= 3 and parts[-2] == "image":
        return parts[-1]
    # Other API paths: /api/link/<id>, /api/decode/<id>
    if len(parts) >= 3 and parts[-2] in ("link", "decode"):
        return parts[-1]

    return None


def _normalize_url(url):
    """Convert a view URL to an API image URL.

    Accepts:
      - https://temporalcloak.cloud/view.html?id=a1b2c3d4
      - https://temporalcloak.cloud/api/image/a1b2c3d4
      - https://temporalcloak.cloud/api/image  (random)
    """
    link_id = _extract_link_id(url)
    if link_id is not None:
        parsed = urlparse(url)
        if parsed.scheme:
            return f"{parsed.scheme}://{parsed.netloc}/api/image/{link_id}"
        return f"https://temporalcloak.cloud/api/image/{link_id}"
    return url


class DecodeSession:
    """Manages the state and lifecycle of a single CLI decode operation."""

    def __init__(self, url: str, debug: bool = False):
        self._url = _normalize_url(url)
        self._debug = debug
        self._console = Console()
        self._server_config = None
        self._cloak = None
        self._total_bytes = 0
        self._gap_count = 0
        self._start_time = None

    def __repr__(self):
        return f"DecodeSession(url={self._url!r}, debug={self._debug})"

    def run(self):
        """Orchestrate the full decode: fetch config, connect, stream, display results."""
        self._console.print(f"[bold]Connecting to[/bold] {self._url}\n")

        self._fetch_server_config()
        response = self._connect()

        chunk_size = TemporalCloakConst.CHUNK_SIZE_TORNADO
        content_length = int(response.headers.get("Content-Length", 0))
        total_gaps = math.ceil(content_length / chunk_size) - 1 if content_length else 0

        self._cloak = AutoDecoder(total_gaps, debug=False)

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self._console,
        )
        task = progress.add_task("Receiving", total=total_gaps + 1)

        first_chunk = True
        with Live(self._build_display(progress), console=self._console, refresh_per_second=12) as live:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    self._total_bytes += len(chunk)
                    if first_chunk:
                        self._cloak.start_timer()
                        self._start_time = time.monotonic()
                        first_chunk = False
                    else:
                        self._process_chunk()

                    progress.update(task, advance=1)
                    live.update(self._build_display(progress))

        self._console.print()
        if self._cloak.message_complete and self._cloak.message:
            pass  # Already displayed in the live panel above
        else:
            self._display_diagnostics()

        if self._debug:
            self._display_debug_stats()

        self._save_timing_data()

    def _collect_timing_data(self):
        """Build a dict of all timing data from the current decode session."""
        link_id = _extract_link_id(self._url)
        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0

        return {
            "version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": self._url,
            "link_id": link_id,
            "result": {
                "message": self._cloak.message if self._cloak else "",
                "message_complete": self._cloak.message_complete if self._cloak else False,
                "checksum_valid": self._cloak.checksum_valid if self._cloak else None,
                "mode": self._cloak.mode if self._cloak else None,
                "bit_count": self._cloak.bit_count if self._cloak else 0,
                "bits_hex": self._cloak.bits.hex if self._cloak else "",
                "threshold": self._cloak.threshold if self._cloak else 0.0,
            },
            "timing": {
                "delays": self._cloak.time_delays if self._cloak else [],
                "confidence_scores": self._cloak.confidence_scores if self._cloak else [],
                "total_bytes": self._total_bytes,
                "gap_count": self._gap_count,
                "elapsed_seconds": round(elapsed, 3),
            },
            "server_config": self._server_config,
            "server_debug": None,
        }

    def _fetch_server_debug(self, link_id):
        """Fetch /api/image/<id>/debug from the server, or return None."""
        debug_url = _build_api_url(self._url, link_id, suffix="debug")
        try:
            resp = requests.get(debug_url, timeout=10)
            if resp.ok:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def _save_timing_data(self):
        """Save timing data to data/timing/<link_id>_<timestamp>.json."""
        if not self._cloak:
            return

        data = self._collect_timing_data()

        # Fetch server debug info if we have a link ID
        link_id = data["link_id"]
        if link_id:
            data["server_debug"] = self._fetch_server_debug(link_id)

        # Build filename
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = link_id if link_id else "random"
        filename = f"{prefix}_{ts}.json"

        timing_dir = os.path.join("data", "timing")
        os.makedirs(timing_dir, exist_ok=True)
        filepath = os.path.join(timing_dir, filename)

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        self._console.print(f"\n[dim]Timing data saved to {filepath}[/dim]")

    def _fetch_server_config(self):
        """GET /api/config to retrieve server timing parameters."""
        parsed = urlparse(self._url)
        config_url = f"{parsed.scheme}://{parsed.netloc}/api/config"
        try:
            config_resp = requests.get(config_url, timeout=5)
            if config_resp.ok:
                self._server_config = config_resp.json()
        except requests.RequestException:
            pass

    def _connect(self):
        """Open a streaming HTTP connection to the image URL."""
        try:
            response = requests.get(self._url, stream=True, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            self._console.print(f"[bold red]Connection failed:[/bold red] {e}")
            sys.exit(1)

    def _process_chunk(self):
        """Process one inter-chunk gap: mark time and let AutoDecoder handle the rest."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._cloak.mark_time()
        self._gap_count += 1

    def _build_display(self, progress) -> Group:
        """Build the Rich renderable group (progress + stats + message panel)."""
        parts = []
        parts.append(progress.get_renderable())

        stats = Table(show_header=False, border_style="dim", padding=(0, 1))
        stats.add_column("Key", style="dim", min_width=12)
        stats.add_column("Value", min_width=20)

        mode = (self._cloak.mode or "detecting...") if self._cloak else "detecting..."
        stats.add_row("Mode", mode)
        stats.add_row("Bits decoded", str(self._cloak.bit_count) if self._cloak else "0")

        if self._cloak:
            collected, needed = self._cloak.bootstrap_progress
            if not self._cloak.start_boundary_found:
                stats.add_row("Boundaries", f"start: [yellow]{collected}/{needed} bits[/yellow]")
            elif not self._cloak.end_boundary_found:
                stats.add_row("Boundaries", "[green]start: found[/green]  end: [yellow]waiting[/yellow]")
            else:
                stats.add_row("Boundaries", "[green]start: found[/green]  [green]end: found[/green]")

        if self._server_config:
            bit1 = self._server_config.get("bit_1_delay", 0)
            bit0 = self._server_config.get("bit_0_delay", 0)
            stats.add_row("Server delays", f"bit1={bit1:.3f}s  bit0={bit0:.3f}s")

        if self._cloak:
            stats.add_row("Threshold", f"{self._cloak.threshold:.4f}s")

            scores = self._cloak.confidence_scores
            if scores:
                avg_conf = sum(scores) / len(scores)
                stats.add_row("Confidence", f"{avg_conf:.1%}")

        if self._start_time:
            elapsed = time.monotonic() - self._start_time
            stats.add_row("Elapsed", f"{elapsed:.1f}s")

        parts.append(stats)

        current_message = self._cloak.message if self._cloak else ""
        is_complete = self._cloak.message_complete if self._cloak else False

        if current_message or is_complete:
            if is_complete:
                checksum_ok = self._cloak.checksum_valid
                if checksum_ok:
                    status = Text(" checksum valid ", style="bold green")
                    border = "green"
                elif checksum_ok is False:
                    status = Text(" checksum failed ", style="bold red")
                    border = "red"
                else:
                    status = Text(" no checksum ", style="yellow")
                    border = "yellow"
            else:
                status = Text(" decoding... ", style="bold cyan")
                border = "cyan"

            msg_text = Text(current_message, style="bold white")
            panel = Panel(
                msg_text,
                title="Message",
                subtitle=status,
                border_style=border,
                padding=(1, 2),
            )
            parts.append(panel)

        return Group(*parts)

    def _display_diagnostics(self):
        """Show failure diagnostics explaining why decoding failed."""
        self._console.print("[bold red]Could not decode a message.[/bold red]\n")

        diag = Table(title="Diagnostics", show_header=False, border_style="yellow")
        diag.add_column("Check", style="dim")
        diag.add_column("Result")

        diag.add_row("Total bits", str(self._cloak.bit_count))

        if self._cloak.delegate:
            from temporal_cloak.decoding import TemporalCloakDecoding
            bits = self._cloak.bits
            boundary = self._cloak.boundary
            boundary_len = self._cloak.boundary_len

            start_boundary = TemporalCloakDecoding.find_boundary(
                bits, boundary_hex=boundary
            )
            mode_label = self._cloak.mode or "none"
            if start_boundary is not None:
                diag.add_row("Mode", f"[green]{mode_label}[/green]")
                diag.add_row("Start boundary", f"[green]found at bit {start_boundary}[/green]")
                end_boundary = TemporalCloakDecoding.find_boundary(
                    bits, start_boundary + boundary_len,
                    boundary_hex=boundary
                )
                if end_boundary is not None:
                    diag.add_row("End boundary", f"[green]found at bit {end_boundary}[/green]")
                else:
                    diag.add_row("End boundary", "[red]NOT FOUND[/red] — end marker missing or corrupted")
            else:
                diag.add_row("Mode", f"[yellow]{mode_label}[/yellow] (detected during bootstrap but lost after recalibration)")
                diag.add_row("Start boundary", "[red]NOT FOUND[/red] — recalibration likely flipped boundary bits")

            msg, completed, _ = self._cloak.bits_to_message()
            if msg:
                printable = "".join(c if 32 <= ord(c) < 127 else "?" for c in msg)
                diag.add_row("Partial decode", f"[dim]{printable[:80]}[/dim]")

            delays = self._cloak.time_delays
            if delays:
                short = [d for d in delays if d <= self._cloak.threshold]
                long = [d for d in delays if d > self._cloak.threshold]
                if short:
                    diag.add_row("Avg short delay", f"{sum(short)/len(short):.4f}s ({len(short)} bits)")
                if long:
                    diag.add_row("Avg long delay", f"{sum(long)/len(long):.4f}s ({len(long)} bits)")

        self._console.print(diag)
        self._console.print("\n[dim]Possible causes: network jitter corrupted timing, "
                          "or server delays are too small for this connection.[/dim]")

    def _display_debug_stats(self):
        """Show debug statistics table."""
        table = Table(title="Debug Stats", show_header=False, border_style="dim")
        table.add_column("Key", style="dim")
        table.add_column("Value")

        mode = self._cloak.mode or "unknown"
        table.add_row("Mode", mode)
        table.add_row("Total bytes", f"{self._total_bytes:,}")
        table.add_row("Gaps processed", str(self._gap_count))
        table.add_row("Bits decoded", str(len(self._cloak.bits)))
        table.add_row("Threshold", f"{self._cloak.threshold:.4f}s")

        scores = self._cloak.confidence_scores
        if scores:
            avg_conf = sum(scores) / len(scores)
            min_conf = min(scores)
            table.add_row("Avg confidence", f"{avg_conf:.2%}")
            table.add_row("Min confidence", f"{min_conf:.2%}")

        if self._start_time:
            elapsed = time.monotonic() - self._start_time
            table.add_row("Total time", f"{elapsed:.1f}s")

        self._console.print()
        self._console.print(table)


@click.group()
@click.version_option()
def cli():
    """TemporalCloak - decode secret messages hidden in timing delays."""
    pass


@cli.command()
@click.argument("url", default=DEFAULT_URL)
@click.option("--debug", is_flag=True, help="Show debug output (raw bits, delays).")
def decode(url, debug):
    """Decode a hidden message from a TemporalCloak image URL.

    URL defaults to the production server at temporalcloak.cloud.
    """
    DecodeSession(url, debug).run()


def _build_api_url(url, link_id, suffix=None):
    """Build an API image URL, optionally with a suffix like /debug or /normal."""
    parsed = urlparse(url)
    base = parsed.scheme and f"{parsed.scheme}://{parsed.netloc}" or "https://temporalcloak.cloud"
    path = f"/api/image/{link_id}"
    if suffix:
        path = f"{path}/{suffix}"
    return f"{base}{path}"


@cli.command(name="debug")
@click.argument("url")
def debug_link(url):
    """Show the encoding debug info for a link.

    URL can be a view URL, API image URL, or a bare link ID.
    """
    console = Console()
    link_id = _extract_link_id(url)
    if link_id is None:
        console.print("[bold red]Error:[/bold red] Cannot extract link ID from URL.")
        sys.exit(1)
    debug_url = _build_api_url(url, link_id, suffix="debug")

    console.print(f"[bold]Fetching debug info for[/bold] {link_id}\n")

    try:
        resp = requests.get(debug_url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    data = resp.json()

    # Header info
    info = Table(show_header=False, border_style="dim", padding=(0, 1))
    info.add_column("Key", style="dim", min_width=16)
    info.add_column("Value")
    info.add_row("Link ID", data["id"])
    info.add_row("Mode", data["mode"])
    info.add_row("Image", data["image_filename"])
    info.add_row("Image size", f"{data['image_size']:,} bytes")
    info.add_row("Total chunks", str(data["total_chunks"]))
    info.add_row("Total gaps", str(data["total_gaps"]))
    info.add_row("Signal bits", str(data["signal_bit_count"]))
    console.print(info)
    console.print()

    # Message panel
    console.print(Panel(
        Text(data["message"], style="bold white"),
        title="Message",
        border_style="green",
        padding=(1, 2),
    ))
    console.print()

    # Sections table
    sections_table = Table(title="Bit Sections", border_style="dim")
    sections_table.add_column("Section", style="bold")
    sections_table.add_column("Offset", justify="right")
    sections_table.add_column("Length", justify="right")
    sections_table.add_column("Bits", overflow="fold")
    sections_table.add_column("Detail")

    for s in data["sections"]:
        detail = ""
        if "text" in s:
            detail = f'"{s["text"]}"'
        elif "value" in s:
            detail = str(s["value"])
        elif "hex" in s:
            detail = f'0x{s["hex"]}'

        bits_str = s["bits"] if s["bits"] else "?"
        sections_table.add_row(
            s["label"],
            str(s["offset"]),
            str(s["length"]),
            bits_str,
            detail,
        )

    console.print(sections_table)
    console.print()

    # Full signal bits
    console.print(Panel(
        Text(data["signal_bits"], style="dim"),
        title=f"Signal Bits ({data['signal_bit_count']} bits)",
        subtitle=f"hex: {data['signal_bits_hex']}",
        border_style="dim",
    ))


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--limit", type=int, default=0, help="Max rows in per-bit table (0 = all).")
def timing(file, limit):
    """Display saved timing data from a previous decode session.

    FILE is a JSON file saved by the decode command (in data/timing/).
    """
    console = Console()

    with open(file) as f:
        data = json.load(f)

    _timing_summary(console, data)
    console.print()
    _timing_per_bit(console, data, limit)
    console.print()
    _timing_histogram(console, data)

    if data.get("server_debug"):
        console.print()
        _timing_server_comparison(console, data)


def _timing_summary(console, data):
    """Display the summary table."""
    result = data.get("result", {})
    timing = data.get("timing", {})
    server_config = data.get("server_config") or {}

    table = Table(title="Summary", show_header=False, border_style="dim")
    table.add_column("Key", style="dim", min_width=16)
    table.add_column("Value")

    table.add_row("Mode", result.get("mode") or "unknown")
    table.add_row("Message", result.get("message") or "(none)")

    checksum = result.get("checksum_valid")
    if checksum is True:
        table.add_row("Checksum", "[green]valid[/green]")
    elif checksum is False:
        table.add_row("Checksum", "[red]failed[/red]")
    else:
        table.add_row("Checksum", "[yellow]n/a[/yellow]")

    table.add_row("Threshold", f"{result.get('threshold', 0):.4f}s")
    table.add_row("Elapsed", f"{timing.get('elapsed_seconds', 0):.1f}s")
    table.add_row("Total bits", str(result.get("bit_count", 0)))
    table.add_row("Total bytes", f"{timing.get('total_bytes', 0):,}")
    table.add_row("Gap count", str(timing.get("gap_count", 0)))

    if server_config:
        bit1 = server_config.get("bit_1_delay", 0)
        bit0 = server_config.get("bit_0_delay", 0)
        table.add_row("Server delays", f"bit1={bit1:.3f}s  bit0={bit0:.3f}s")

    console.print(table)


def _timing_per_bit(console, data, limit):
    """Display the per-bit timing table."""
    result = data.get("result", {})
    timing = data.get("timing", {})
    delays = timing.get("delays", [])
    scores = timing.get("confidence_scores", [])
    bits_hex = result.get("bits_hex", "")
    mode = result.get("mode", "frontloaded")

    # Convert hex to binary string
    if bits_hex:
        bit_count = result.get("bit_count", 0)
        bits_bin = bin(int(bits_hex, 16))[2:].zfill(len(bits_hex) * 4)
        # Trim to actual bit count
        if bit_count and bit_count < len(bits_bin):
            bits_bin = bits_bin[:bit_count]
    else:
        bits_bin = ""

    # Determine preamble length and end boundary for phase labeling
    from temporal_cloak.const import TemporalCloakConst
    boundary_len = 16
    if mode == "distributed":
        preamble_len = TemporalCloakConst.PREAMBLE_BITS
    else:
        preamble_len = boundary_len

    bit_count = result.get("bit_count", 0)
    message_complete = result.get("message_complete", False)
    end_boundary_start = bit_count - boundary_len if message_complete and bit_count > boundary_len else None

    table = Table(title="Per-Bit Timing", border_style="dim")
    table.add_column("Index", justify="right", style="dim")
    table.add_column("Delay (s)", justify="right")
    table.add_column("Bit", justify="center")
    table.add_column("Confidence", justify="right")
    table.add_column("Phase")

    row_count = min(len(delays), len(bits_bin)) if bits_bin else len(delays)
    display_count = min(row_count, limit) if limit > 0 else row_count

    for i in range(display_count):
        delay = delays[i] if i < len(delays) else 0
        bit = bits_bin[i] if i < len(bits_bin) else "?"
        conf = scores[i] if i < len(scores) else 0

        # Color-code confidence
        if conf < 0.2:
            conf_style = "bold red"
        elif conf < 0.5:
            conf_style = "yellow"
        else:
            conf_style = "green"

        # Determine phase
        if i < boundary_len:
            phase = "boundary"
        elif i < preamble_len:
            phase = "preamble"
        elif end_boundary_start is not None and i >= end_boundary_start:
            phase = "end boundary"
        else:
            phase = "payload"

        table.add_row(
            str(i),
            f"{delay:.4f}",
            bit,
            Text(f"{conf:.2f}", style=conf_style),
            phase,
        )

    if display_count < row_count:
        table.add_row("...", f"({row_count - display_count} more)", "", "", "")

    console.print(table)


def _timing_histogram(console, data):
    """Display a text-based delay histogram with threshold marker."""
    delays = data.get("timing", {}).get("delays", [])
    threshold = data.get("result", {}).get("threshold", 0)

    if not delays:
        return

    min_d = min(delays)
    max_d = max(delays)

    if max_d == min_d:
        console.print("[dim]All delays identical — no histogram to show.[/dim]")
        return

    num_buckets = 10
    bucket_width = (max_d - min_d) / num_buckets
    buckets = [0] * num_buckets

    for d in delays:
        idx = int((d - min_d) / bucket_width)
        idx = min(idx, num_buckets - 1)
        buckets[idx] += 1

    max_count = max(buckets)
    bar_max_width = 40

    console.print(Text("Delay Histogram", style="bold"))
    console.print(Text(f"  Range: {min_d:.4f}s — {max_d:.4f}s  |  Threshold: {threshold:.4f}s", style="dim"))
    console.print()

    block_chars = "▏▎▍▌▋▊▉█"

    for i in range(num_buckets):
        lo = min_d + i * bucket_width
        hi = lo + bucket_width
        count = buckets[i]

        # Build bar
        if max_count > 0:
            frac = count / max_count
            full_width = frac * bar_max_width
            full_blocks = int(full_width)
            remainder = full_width - full_blocks
            partial_idx = int(remainder * len(block_chars))

            bar = "█" * full_blocks
            if partial_idx > 0 and full_blocks < bar_max_width:
                bar += block_chars[partial_idx - 1]
        else:
            bar = ""

        # Mark threshold bucket
        marker = ""
        if lo <= threshold < hi:
            marker = " ◄ threshold"

        label = f"  {lo:7.4f}s "
        console.print(Text(f"{label}{bar} {count}{marker}"))


def _timing_server_comparison(console, data):
    """Display server vs client bit comparison."""
    server_debug = data.get("server_debug", {})
    result = data.get("result", {})

    signal_bits = server_debug.get("signal_bits", "")
    bits_hex = result.get("bits_hex", "")
    bit_count = result.get("bit_count", 0)
    scores = data.get("timing", {}).get("confidence_scores", [])

    if not signal_bits or not bits_hex:
        return

    # Convert client hex to binary
    client_bits = bin(int(bits_hex, 16))[2:].zfill(len(bits_hex) * 4)
    if bit_count and bit_count < len(client_bits):
        client_bits = client_bits[:bit_count]

    compare_len = min(len(signal_bits), len(client_bits))

    table = Table(title="Server vs Client Comparison", border_style="dim")
    table.add_column("Index", justify="right", style="dim")
    table.add_column("Expected", justify="center")
    table.add_column("Observed", justify="center")
    table.add_column("Match", justify="center")
    table.add_column("Confidence", justify="right")

    mismatches = 0
    for i in range(compare_len):
        expected = signal_bits[i]
        observed = client_bits[i]
        match = expected == observed
        conf = scores[i] if i < len(scores) else 0

        if match:
            match_text = Text("✓", style="green")
            observed_text = Text(observed)
        else:
            match_text = Text("✗", style="bold red")
            observed_text = Text(observed, style="bold red")
            mismatches += 1

        conf_text = Text(f"{conf:.2f}", style="red" if conf < 0.2 else "yellow" if conf < 0.5 else "green")

        table.add_row(str(i), expected, observed_text, match_text, conf_text)

    console.print(table)
    console.print(f"\n[dim]{compare_len} bits compared, {mismatches} mismatches[/dim]")
