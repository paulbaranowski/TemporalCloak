#!/usr/bin/env python3
"""Decode accuracy benchmark for TemporalCloak.

Creates links on a running server, streams each image back, decodes via
AutoDecoder, and compares against ground truth from the debug endpoint.
Produces per-run metrics and aggregate statistics.

Usage:
    uv run python scripts/benchmark.py [OPTIONS]
"""

import json
import math
import os
import random
import statistics
import sys
import time
import warnings
from datetime import datetime, timezone

import click
import requests
from rich.console import Console, Group
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text

from temporal_cloak.const import TemporalCloakConst
from temporal_cloak.decoding import AutoDecoder
from temporal_cloak.quote_provider import QuoteProvider

console = Console()


# ── Server helpers ──────────────────────────────────────────────────

def health_check(base_url: str) -> None:
    """Verify the server is reachable."""
    try:
        resp = requests.get(f"{base_url}/api/health", timeout=5)
        resp.raise_for_status()
    except requests.RequestException as e:
        console.print(f"[bold red]Server unreachable:[/bold red] {e}")
        sys.exit(1)


def pick_largest_image(base_url: str) -> str:
    """Fetch image list and return the filename of the largest image."""
    resp = requests.get(f"{base_url}/api/images", timeout=5)
    resp.raise_for_status()
    images = resp.json()
    if not images:
        console.print("[bold red]No images available on server.[/bold red]")
        sys.exit(1)
    largest = max(images, key=lambda img: img.get("size", 0))
    return largest["filename"]


def create_link(base_url: str, message: str, image: str, mode: str) -> str:
    """POST /api/create and return the link ID."""
    resp = requests.post(
        f"{base_url}/api/create",
        json={"message": message, "image": image, "mode": mode},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def decode_link(base_url: str, link_id: str,
                on_chunk=None) -> dict:
    """Stream-decode an image link and return raw decode results.

    on_chunk(gap_count, total_gaps, decoder) is called after each gap
    so the caller can update progress displays.
    """
    url = f"{base_url}/api/image/{link_id}"
    chunk_size = TemporalCloakConst.CHUNK_SIZE_TORNADO

    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    content_length = int(response.headers.get("Content-Length", 0))
    total_gaps = math.ceil(content_length / chunk_size) - 1 if content_length else 0

    decoder = AutoDecoder(total_gaps)
    first_chunk = True
    start_time = None
    gap_count = 0

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not chunk:
                continue
            if first_chunk:
                decoder.start_timer()
                start_time = time.monotonic()
                first_chunk = False
            else:
                decoder.mark_time()
                gap_count += 1
                if on_chunk:
                    on_chunk(gap_count, total_gaps, decoder)
                if decoder.message_complete:
                    break

    elapsed = time.monotonic() - start_time if start_time else 0.0

    return {
        "message": decoder.message if decoder.message_complete else decoder.partial_message,
        "message_complete": decoder.message_complete,
        "checksum_valid": decoder.checksum_valid,
        "mode_detected": decoder.mode,
        "bit_count": decoder.bit_count,
        "bits_hex": decoder.bits.hex if decoder.bits else "",
        "threshold": decoder.threshold,
        "confidence_scores": list(decoder.confidence_scores),
        "time_delays": list(decoder.time_delays),
        "elapsed_seconds": round(elapsed, 3),
        "gap_count": gap_count,
    }


def fetch_debug(base_url: str, link_id: str) -> dict:
    """GET /api/image/<id>/debug for server ground truth."""
    resp = requests.get(f"{base_url}/api/image/{link_id}/debug", timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── Metric computation ──────────────────────────────────────────────

def compute_bit_error_rate(client_bits_hex: str, client_bit_count: int,
                           server_signal_bits: str) -> dict:
    """Compare client-observed bits against server signal bits."""
    if not client_bits_hex or not server_signal_bits:
        return {"bit_error_rate": None, "mismatch_count": 0, "compare_len": 0}

    client_bits = bin(int(client_bits_hex, 16))[2:].zfill(len(client_bits_hex) * 4)
    if client_bit_count and client_bit_count < len(client_bits):
        client_bits = client_bits[:client_bit_count]

    compare_len = min(len(server_signal_bits), len(client_bits))
    if compare_len == 0:
        return {"bit_error_rate": None, "mismatch_count": 0, "compare_len": 0}

    mismatches = sum(
        1 for i in range(compare_len)
        if server_signal_bits[i] != client_bits[i]
    )
    return {
        "bit_error_rate": mismatches / compare_len,
        "mismatch_count": mismatches,
        "compare_len": compare_len,
    }


def compute_char_error_rate(decoded: str, original: str) -> float:
    """Positional character comparison — no external deps."""
    max_len = max(len(decoded), len(original))
    if max_len == 0:
        return 0.0
    errors = sum(
        1 for i in range(max_len)
        if i >= len(decoded) or i >= len(original) or decoded[i] != original[i]
    )
    return errors / max_len


def build_run_data(result: dict, debug: dict, mode: str) -> dict:
    """Combine decode result + server debug into a single run record."""
    server_message = debug.get("message", "")
    server_signal_bits = debug.get("signal_bits", "")

    bit_info = compute_bit_error_rate(
        result["bits_hex"], result["bit_count"], server_signal_bits
    )

    decoded_msg = result["message"]
    exact_match = decoded_msg == server_message
    char_error_rate = compute_char_error_rate(decoded_msg, server_message)

    scores = result["confidence_scores"]
    conf_stats = {}
    if scores:
        sorted_scores = sorted(scores)
        conf_stats = {
            "mean": statistics.mean(scores),
            "min": min(scores),
            "p5": sorted_scores[max(0, int(len(sorted_scores) * 0.05))],
        }

    return {
        "mode_requested": mode,
        "mode_detected": result["mode_detected"],
        "original_message": server_message,
        "decoded_message": decoded_msg,
        "decode_success": result["message_complete"],
        "checksum_valid": result["checksum_valid"],
        "exact_match": exact_match,
        "bit_error_rate": bit_info["bit_error_rate"],
        "mismatch_count": bit_info["mismatch_count"],
        "compare_len": bit_info["compare_len"],
        "char_error_rate": char_error_rate,
        "confidence": conf_stats,
        "threshold": result["threshold"],
        "elapsed_seconds": result["elapsed_seconds"],
        "bit_count": result["bit_count"],
        "gap_count": result["gap_count"],
        "time_delays": result["time_delays"],
        "confidence_scores": scores,
    }


# ── Live display builder ───────────────────────────────────────────

def build_live_display(progress, tally, completed_runs, verbose) -> Group:
    """Build the Rich renderable group shown during the benchmark."""
    parts = [progress.get_renderable()]

    # Running tally line
    passed = tally["passed"]
    failed = tally["failed"]
    total = passed + failed
    if total > 0:
        tally_text = Text()
        tally_text.append(f"  {passed}", style="green")
        tally_text.append(f" passed  ", style="dim")
        tally_text.append(f"{failed}", style="red" if failed else "dim")
        tally_text.append(f" failed", style="dim")
        if total > 0:
            rate = passed / total
            tally_text.append(f"  ({rate:.0%} success)", style="bold" if rate == 1.0 else "yellow")
        parts.append(tally_text)

    # Verbose: show last few completed runs
    if verbose and completed_runs:
        recent = completed_runs[-8:]
        tbl = Table(show_header=True, border_style="dim", padding=(0, 1),
                    show_edge=False)
        tbl.add_column("#", style="dim", width=4, justify="right")
        tbl.add_column("Result", width=6, justify="center")
        tbl.add_column("Mode", width=12)
        tbl.add_column("BER", width=8, justify="right")
        tbl.add_column("Conf", width=6, justify="right")
        tbl.add_column("Time", width=7, justify="right")
        tbl.add_column("Message", overflow="ellipsis", max_width=42, no_wrap=True)

        for entry in recent:
            idx, run = entry
            status = Text("PASS", style="green") if run["exact_match"] else Text("FAIL", style="bold red")
            ber = f"{run['bit_error_rate']:.4f}" if run["bit_error_rate"] is not None else "n/a"
            conf = f"{run['confidence'].get('mean', 0):.2f}"
            t = f"{run['elapsed_seconds']:.1f}s"
            msg = run["original_message"][:42]
            tbl.add_row(str(idx), status, run["mode_requested"], ber, conf, t, msg)

        parts.append(tbl)

    return Group(*parts)


# ── Aggregation ─────────────────────────────────────────────────────

def aggregate_runs(runs: list[dict], label: str) -> dict:
    """Compute aggregate metrics for a list of runs."""
    if not runs:
        return {"label": label, "count": 0}

    successes = sum(1 for r in runs if r["decode_success"])
    checksum_passes = sum(1 for r in runs if r["checksum_valid"])
    exact_matches = sum(1 for r in runs if r["exact_match"])
    n = len(runs)

    bers = [r["bit_error_rate"] for r in runs if r["bit_error_rate"] is not None]
    sorted_bers = sorted(bers) if bers else []

    all_conf_means = [r["confidence"]["mean"] for r in runs if r.get("confidence", {}).get("mean") is not None]
    all_conf_mins = [r["confidence"]["min"] for r in runs if r.get("confidence", {}).get("min") is not None]

    elapsed = [r["elapsed_seconds"] for r in runs]
    sorted_elapsed = sorted(elapsed)

    mode_correct = sum(
        1 for r in runs if r["mode_detected"] == r["mode_requested"]
    )

    def percentile(sorted_list, p):
        if not sorted_list:
            return None
        idx = int(len(sorted_list) * p)
        return sorted_list[min(idx, len(sorted_list) - 1)]

    return {
        "label": label,
        "count": n,
        "success_rate": successes / n,
        "checksum_pass_rate": checksum_passes / n,
        "exact_match_rate": exact_matches / n,
        "bit_error_rate": {
            "mean": statistics.mean(sorted_bers) if sorted_bers else None,
            "median": statistics.median(sorted_bers) if sorted_bers else None,
            "p95": percentile(sorted_bers, 0.95),
            "max": max(sorted_bers) if sorted_bers else None,
        },
        "confidence": {
            "mean": statistics.mean(all_conf_means) if all_conf_means else None,
            "min": min(all_conf_mins) if all_conf_mins else None,
            "q25": percentile(sorted(all_conf_means), 0.25) if all_conf_means else None,
            "q75": percentile(sorted(all_conf_means), 0.75) if all_conf_means else None,
        },
        "elapsed_seconds": {
            "mean": statistics.mean(elapsed) if elapsed else None,
            "median": statistics.median(elapsed) if elapsed else None,
            "p95": percentile(sorted_elapsed, 0.95),
        },
        "mode_detection_accuracy": mode_correct / n,
    }


def print_summary(aggregates: list[dict]) -> None:
    """Print a Rich summary table from aggregate dicts."""
    table = Table(title="Benchmark Results", border_style="dim")
    table.add_column("Mode", style="bold")
    table.add_column("Runs", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Exact Match", justify="right")
    table.add_column("BER", justify="right")
    table.add_column("Conf Mean", justify="right")
    table.add_column("Avg Time", justify="right")

    for agg in aggregates:
        if agg["count"] == 0:
            continue
        ber = agg["bit_error_rate"]
        conf = agg["confidence"]
        elapsed = agg["elapsed_seconds"]

        ber_str = f"{ber['mean']:.4f}" if ber["mean"] is not None else "n/a"
        conf_str = f"{conf['mean']:.2f}" if conf["mean"] is not None else "n/a"
        elapsed_str = f"{elapsed['mean']:.1f}s" if elapsed["mean"] is not None else "n/a"

        table.add_row(
            agg["label"],
            str(agg["count"]),
            f"{agg['success_rate']:.0%}",
            f"{agg['exact_match_rate']:.0%}",
            ber_str,
            conf_str,
            elapsed_str,
        )

    console.print(table)


# ── Main ────────────────────────────────────────────────────────────

@click.command()
@click.option("--base-url", default="http://localhost:8888", help="Server URL.")
@click.option("--num-quotes", default=10, type=int, help="Number of quotes to test.")
@click.option("--mode", "run_mode", default="both",
              type=click.Choice(["both", "frontloaded", "distributed"]),
              help="Encoding mode(s) to benchmark.")
@click.option("--output", "output_path", default=None, type=click.Path(),
              help="JSON output path [default: data/benchmarks/<timestamp>.json].")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility.")
@click.option("--verbose", is_flag=True, help="Print per-run details.")
def main(base_url, num_quotes, run_mode, output_path, seed, verbose):
    """Benchmark decode accuracy across many messages."""
    from rich.live import Live

    base_url = base_url.rstrip("/")

    console.print(f"[bold]TemporalCloak Decode Benchmark[/bold]")
    console.print(f"Server: {base_url}  Quotes: {num_quotes}  Mode: {run_mode}")
    if seed is not None:
        console.print(f"Seed: {seed}")
    console.print()

    # 1. Health check
    console.print("[dim]Checking server health...[/dim]", end=" ")
    health_check(base_url)
    console.print("[green]ok[/green]")

    # 2. Pick largest image
    console.print("[dim]Fetching image list...[/dim]", end=" ")
    image = pick_largest_image(base_url)
    console.print(f"[green]{image}[/green]")

    # 3. Load quotes
    console.print("[dim]Loading quotes...[/dim]", end=" ")
    if seed is not None:
        random.seed(seed)
    provider = QuoteProvider()
    quotes = [provider.get_encodable_quote() for _ in range(num_quotes)]
    console.print(f"[green]{len(quotes)} encodable quotes selected[/green]")
    console.print()

    # 4. Determine modes to run
    modes = ["frontloaded", "distributed"] if run_mode == "both" else [run_mode]
    total_runs = len(quotes) * len(modes)

    # 5. Run benchmarks with live progress
    all_runs = []
    runs_by_mode = {m: [] for m in modes}
    tally = {"passed": 0, "failed": 0}
    completed_runs = []  # list of (index, run_data) for verbose display

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        TextColumn("[dim]{task.fields[step]}[/dim]"),
        console=console,
    )
    overall_task = progress.add_task(
        "Benchmarking", total=total_runs, step="starting..."
    )

    run_index = 0
    with Live(
        build_live_display(progress, tally, completed_runs, verbose),
        console=console, refresh_per_second=12,
    ) as live:
        for mode in modes:
            for quote in quotes:
                run_index += 1
                short_msg = quote[:30] + ("..." if len(quote) > 30 else "")

                # Step 1: Create link
                progress.update(
                    overall_task,
                    description=f"[bold]{mode}[/bold] {run_index}/{total_runs}",
                    step=f"creating link: {short_msg}",
                )
                live.update(build_live_display(progress, tally, completed_runs, verbose))
                link_id = create_link(base_url, quote, image, mode)

                # Step 2: Stream & decode
                def on_chunk(gap_count, total_gaps, decoder):
                    pct = gap_count / total_gaps if total_gaps else 0
                    bits = decoder.bit_count
                    partial = decoder.partial_message
                    step_text = f"streaming {gap_count}/{total_gaps} gaps, {bits} bits"
                    if partial:
                        preview = partial[:20] + ("..." if len(partial) > 20 else "")
                        step_text += f' "{preview}"'
                    progress.update(overall_task, step=step_text)
                    # Throttle live updates to every 10 chunks
                    if gap_count % 10 == 0:
                        live.update(build_live_display(progress, tally, completed_runs, verbose))

                progress.update(overall_task, step=f"streaming {link_id}...")
                live.update(build_live_display(progress, tally, completed_runs, verbose))
                result = decode_link(base_url, link_id, on_chunk=on_chunk)

                # Step 3: Fetch debug
                progress.update(overall_task, step="fetching server debug...")
                live.update(build_live_display(progress, tally, completed_runs, verbose))
                debug = fetch_debug(base_url, link_id)

                # Step 4: Compare
                progress.update(overall_task, step="comparing...")
                live.update(build_live_display(progress, tally, completed_runs, verbose))
                run_data = build_run_data(result, debug, mode)
                run_data["link_id"] = link_id

                # Update tally
                if run_data["exact_match"]:
                    tally["passed"] += 1
                else:
                    tally["failed"] += 1

                all_runs.append(run_data)
                runs_by_mode[mode].append(run_data)
                completed_runs.append((run_index, run_data))

                progress.update(overall_task, advance=1, step="done")
                live.update(build_live_display(progress, tally, completed_runs, verbose))

    console.print()

    # 6. Aggregate and display
    aggregates = []
    for mode in modes:
        aggregates.append(aggregate_runs(runs_by_mode[mode], mode))
    if len(modes) > 1:
        aggregates.append(aggregate_runs(all_runs, "overall"))

    print_summary(aggregates)

    # 7. Save JSON report
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join("data", "benchmarks", f"{ts}.json")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    report = {
        "version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "base_url": base_url,
            "num_quotes": num_quotes,
            "mode": run_mode,
            "seed": seed,
            "image": image,
        },
        "aggregates": aggregates,
        "runs": all_runs,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    console.print(f"\n[dim]Report saved to {output_path}[/dim]")


if __name__ == "__main__":
    main()
