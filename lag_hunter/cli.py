from __future__ import annotations
import argparse, sys
from .probe import probe, valid_target, ProbeError
from .report import analyse, render, to_json


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lag_hunter", description="Per-hop latency and loss to one target, with a heuristic suspect hop. Probes only the target you name and the hop addresses the trace prints.")
    ap.add_argument("--target", help="host name or address to trace and ping")
    ap.add_argument("--count", type=int, default=20, help="pings per hop (1-500, default 20)")
    ap.add_argument("--timeout-ms", type=int, default=1000, help="wait per reply in ms (default 1000)")
    ap.add_argument("--max-hops", type=int, default=30, help="trace hop limit (1-64, default 30)")
    ap.add_argument("--from-file", metavar="CAPTURE", help="read a saved capture instead of probing (no network)")
    ap.add_argument("--save", metavar="CAPTURE", help="write the raw capture of a live probe to this file")
    ap.add_argument("--lat-jump", type=float, default=20.0, help="ms rise that counts as a jump (default 20)")
    ap.add_argument("--loss-jump", type=float, default=5.0, help="loss points rise that counts as a jump (default 5)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the table")
    return ap


def main(argv=None) -> int:
    ap = build_parser(); a = ap.parse_args(argv)
    if a.from_file and a.target:
        ap.error("use either --target or --from-file, not both")
    if not a.from_file and not a.target:
        ap.error("--target is required (or --from-file)")
    if a.from_file and a.save:
        ap.error("--save only applies to a live probe")
    if a.target and not valid_target(a.target):
        ap.error(f"--target is not a valid host name or address: {a.target!r}")
    if not 1 <= a.count <= 500: ap.error("--count must be 1-500")
    if not 1 <= a.max_hops <= 64: ap.error("--max-hops must be 1-64")
    if not 100 <= a.timeout_ms <= 10000: ap.error("--timeout-ms must be 100-10000")
    if a.lat_jump <= 0 or a.loss_jump <= 0: ap.error("--lat-jump and --loss-jump must be positive")
    try:
        if a.from_file:
            with open(a.from_file, encoding="utf-8", errors="replace") as f:
                text = f.read()
        else:
            text = probe(a.target, a.count, a.timeout_ms, a.max_hops)
            if a.save:
                with open(a.save, "w", encoding="utf-8") as f:
                    f.write(text)
        target, rows, suspect = analyse(text, a.lat_jump, a.loss_jump)
    except (ProbeError, OSError) as e:
        print(f"lag_hunter: {e}", file=sys.stderr); return 1
    print(to_json(target, rows, suspect) if a.json else render(target, rows, suspect, a.lat_jump, a.loss_jump))
    return 0
