import math
import sys
import time
import warnings
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


def _normalize_url(url):
    """Convert a view URL to an API image URL.

    Accepts:
      - https://temporalcloak.cloud/view.html?id=a1b2c3d4
      - https://temporalcloak.cloud/api/image/a1b2c3d4
      - https://temporalcloak.cloud/api/image  (random)
    """
    parsed = urlparse(url)
    if parsed.path.rstrip("/").endswith("view.html"):
        link_id = parse_qs(parsed.query).get("id", [None])[0]
        if not link_id:
            Console().print("[bold red]Error:[/bold red] view URL is missing the ?id= parameter.")
            sys.exit(1)
        return f"{parsed.scheme}://{parsed.netloc}/api/image/{link_id}"
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
