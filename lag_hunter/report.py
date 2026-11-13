"""Per-hop rows and the heuristic suspect hop."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from .probe import Hop, PingResult, parse_tracert, parse_ping, parse_capture


@dataclass
class Row:
    hop: int
    host: str | None
    avg: float | None       # ms, from the pings (or from the trace if there were no pings)
    max: float | None
    loss: float | None      # % of pings lost; None = hop was not pinged
    sent: int
    received: int
    source: str             # "ping", "trace" or "none"


def build_rows(hops: list[Hop], pings: dict[str, PingResult]) -> list[Row]:
    rows = []
    for h in hops:
        p = pings.get(h.host) if h.host else None
        if p is not None and p.sent > 0:
            avg = sum(p.rtts) / len(p.rtts) if p.rtts else None
            rows.append(Row(h.n, h.host, avg, max(p.rtts) if p.rtts else None, 100.0 * (p.sent - p.received) / p.sent, p.sent, p.received, "ping"))
        elif h.rtts:
            rows.append(Row(h.n, h.host, sum(h.rtts) / len(h.rtts), max(h.rtts), None, 0, 0, "trace"))
        else:
            rows.append(Row(h.n, h.host, None, None, None, 0, 0, "none"))
    return rows


def _first_jump(series: list[tuple[int, float]], jump: float) -> int | None:
    """series = [(row index, value)]. First point whose rise over the previous point (0 before the first) is >= jump
    and where every later point stays at least half that rise above the previous point's value."""
    prev = 0.0
    for k, (idx, v) in enumerate(series):
        rise = v - prev
        if rise >= jump and all(w >= prev + rise / 2 for _, w in series[k + 1:]):
            return idx
        prev = v
    return None


def find_suspect(rows: list[Row], lat_jump: float = 20.0, loss_jump: float = 5.0) -> dict | None:
    """Heuristic suspect hop: the first hop where average latency (ms) or ping loss (percentage points) rises by
    at least the threshold over the previous hop with data and the later hops do not fall back to the old level.
    A hop that never answered pings while later hops did is ignored (routers often de-prioritise ICMP)."""
    lat = [(i, r.avg) for i, r in enumerate(rows) if r.avg is not None]
    last_resp = max((i for i, r in enumerate(rows) if r.source == "ping" and r.received > 0), default=-1)
    loss = [(i, r.loss) for i, r in enumerate(rows) if r.loss is not None and (r.received > 0 or i > last_resp)]
    li, si = _first_jump(lat, lat_jump), _first_jump(loss, loss_jump)
    cands = [i for i in (li, si) if i is not None]
    if not cands:
        return None
    i = min(cands)
    why = []
    if li == i:
        before = next((v for j, v in reversed(lat) if j < i), 0.0)
        why.append(f"average latency rises from {before:.1f} ms to {rows[i].avg:.1f} ms and stays up")
    if si == i:
        before = next((v for j, v in reversed(loss) if j < i), 0.0)
        why.append(f"ping loss rises from {before:.0f}% to {rows[i].loss:.0f}% and stays up")
    return {"hop": rows[i].hop, "host": rows[i].host, "reason": "; ".join(why)}


def render(target: str, rows: list[Row], suspect: dict | None, lat_jump: float, loss_jump: float) -> str:
    out = [f"lag-hunter  target {target}", ""]
    out.append(f"{'hop':>3}  {'host':<28} {'avg ms':>8} {'max ms':>8} {'loss %':>7}  note")
    for r in rows:
        note = ""
        if r.host is None:
            note = "no reply to the trace"
        elif r.source == "trace":
            note = "from trace only (not pinged)"
        elif r.received == 0:
            note = "no ping replies"
        if suspect and suspect["hop"] == r.hop:
            note = ("<-- heuristic suspect hop" + (f"; {note}" if note else ""))
        f = lambda v, p: "-" if v is None else f"{v:.{p}f}"
        out.append(f"{r.hop:>3}  {(r.host or '*'):<28} {f(r.avg, 1):>8} {f(r.max, 1):>8} {f(r.loss, 0):>7}  {note}".rstrip())
    out.append("")
    if suspect:
        out.append(f"Heuristic suspect hop: {suspect['hop']} ({suspect['host']}): {suspect['reason']}.")
    else:
        out.append(f"No suspect hop: no hop rose by {lat_jump:g} ms or {loss_jump:g} loss points over the previous one and stayed up.")
    out.append("This is a heuristic on a few pings per hop, not a diagnosis. A router that de-prioritises ICMP can look slow or lossy while forwarding fine.")
    return "\n".join(out)


def analyse(capture_text: str, lat_jump: float, loss_jump: float) -> tuple[str, list[Row], dict | None]:
    target, trace_text, ping_texts = parse_capture(capture_text)
    hops = parse_tracert(trace_text)
    rows = build_rows(hops, {h: parse_ping(t) for h, t in ping_texts.items()})
    return target, rows, find_suspect(rows, lat_jump, loss_jump)


def to_json(target: str, rows: list[Row], suspect: dict | None) -> str:
    return json.dumps({"target": target, "hops": [asdict(r) for r in rows], "suspect": suspect}, indent=2)
