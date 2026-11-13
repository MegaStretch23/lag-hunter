"""Run the system tracert/ping (Windows) or traceroute/ping (other OSes) and parse their text output.

Capture format (used by --save and --from-file): sections introduced by a line
``=== tracert <target> ===`` or ``=== ping <host> ===`` followed by the tool's raw output.
"""
from __future__ import annotations
import re, shutil, subprocess, sys
from dataclasses import dataclass, field

TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:_-]{0,252}$")
IP4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
SECTION_RE = re.compile(r"^=== (tracert|ping) (\S+) ===\s*$")


class ProbeError(Exception):
    pass


@dataclass
class Hop:
    n: int
    host: str | None            # address or name tracert/traceroute printed; None = no reply
    rtts: list = field(default_factory=list)   # ms values from the trace itself (one per answered probe)


@dataclass
class PingResult:
    sent: int
    received: int
    rtts: list                  # ms, received replies only


def valid_target(t: str) -> bool:
    return bool(TARGET_RE.match(t or ""))


def _ms(tok: str) -> float:
    tok = tok.strip().lower().replace("ms", "").strip()
    if tok.startswith("<"):
        return 0.5              # Windows prints "<1 ms"; counted as 0.5
    return float(tok)


_WIN_HOP = re.compile(r"^\s*(\d+)\s+((?:(?:<?\d+(?:\.\d+)?\s*ms|\*)\s+){3})\s*(.*?)\s*$")
_BRACKET = re.compile(r"\[([^\]]+)\]")


def parse_tracert(text: str) -> list[Hop]:
    """Windows `tracert` and Linux `traceroute` (hop lines only; header and footer are ignored)."""
    hops: list[Hop] = []
    for line in text.splitlines():
        m = _WIN_HOP.match(line + " ")
        if m:
            n, probes, rest = int(m.group(1)), m.group(2), m.group(3)
            rtts = [_ms(x) for x in re.findall(r"<?\d+(?:\.\d+)?\s*ms", probes)]
            if not rest or rest.lower().startswith("request timed out"):
                host = None
            else:
                b = _BRACKET.search(rest)
                host = b.group(1) if b else rest.split()[0]
            hops.append(Hop(n, host, rtts))
            continue
        m = re.match(r"^\s*(\d+)\s+(\S.*)$", line)          # traceroute: "2  10.0.0.1  1.2 ms  1.1 ms  1.0 ms" / "3  * * *"
        if m and ("ms" in m.group(2) or m.group(2).replace("*", "").strip() == ""):
            n, rest = int(m.group(1)), m.group(2)
            rtts = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*ms", rest)]
            host = None
            for tok in rest.replace("(", " ").replace(")", " ").split():
                if tok != "*" and not re.fullmatch(r"\d+(\.\d+)?", tok) and tok != "ms" and not tok.startswith("!"):
                    host = tok; break
            hops.append(Hop(n, host, rtts))
    return hops


def parse_ping(text: str) -> PingResult:
    """Windows `ping` and Linux/macOS `ping`. Replies without a time (unreachable, TTL expired) are not replies."""
    rtts = []
    for line in text.splitlines():
        m = re.search(r"\btime\s*([=<])\s*([\d.]+)\s*ms", line, re.I)
        if m:
            rtts.append(0.5 if m.group(1) == "<" else float(m.group(2)))
    sent = None
    m = re.search(r"Sent\s*=\s*(\d+)", text)                 # Windows summary
    if m:
        sent = int(m.group(1))
    else:
        m = re.search(r"(\d+)\s+packets transmitted", text)  # Linux / macOS summary
        if m:
            sent = int(m.group(1))
    if sent is None:                                         # no summary: replies plus timeout lines
        sent = len(rtts) + len(re.findall(r"Request timed out|Destination (?:host|net)\w* unreachable|TTL expired", text, re.I))
    return PingResult(sent=sent, received=min(len(rtts), sent) if sent else 0, rtts=rtts)


def parse_capture(text: str) -> tuple[str, str, dict]:
    """-> (target, tracert text, {host: ping text})."""
    secs: list[tuple[str, str, list]] = []
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            secs.append((m.group(1), m.group(2), [])); continue
        if secs:
            secs[-1][2].append(line)
    trace = [s for s in secs if s[0] == "tracert"]
    if not trace:
        raise ProbeError("capture has no '=== tracert <target> ===' section")
    pings = {h: "\n".join(body) for k, h, body in secs if k == "ping"}
    return trace[0][1], "\n".join(trace[0][2]), pings


def build_capture(target: str, trace_text: str, pings: dict) -> str:
    out = [f"=== tracert {target} ===", trace_text.rstrip("\n")]
    for host, txt in pings.items():
        out += [f"=== ping {host} ===", txt.rstrip("\n")]
    return "\n".join(out) + "\n"


def _run(cmd: list, timeout: float) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    except FileNotFoundError:
        raise ProbeError(f"{cmd[0]} not found on PATH")
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        if not out.strip():
            raise ProbeError(f"{cmd[0]} timed out after {timeout:.0f}s with no output")
        return out
    return r.stdout


def trace_cmd(target: str, max_hops: int, timeout_ms: int, windows: bool) -> list:
    if windows:
        return ["tracert", "-d", "-h", str(max_hops), "-w", str(timeout_ms), target]
    return ["traceroute", "-n", "-m", str(max_hops), "-w", str(max(1, round(timeout_ms / 1000))), "-q", "3", target]


def ping_cmd(host: str, count: int, timeout_ms: int, windows: bool) -> list:
    if windows:
        return ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    return ["ping", "-c", str(count), "-W", str(max(1, round(timeout_ms / 1000))), host]


def probe(target: str, count: int = 20, timeout_ms: int = 1000, max_hops: int = 30, windows: bool | None = None) -> str:
    """Trace to `target`, then ping each hop address the trace printed `count` times. Returns the capture text."""
    if not valid_target(target):
        raise ProbeError(f"not a valid host name or address: {target!r}")
    windows = sys.platform.startswith("win") if windows is None else windows
    tool = "tracert" if windows else "traceroute"
    if not windows and not shutil.which("traceroute"):
        raise ProbeError("traceroute not found on PATH (install it, or use --from-file)")
    trace_text = _run(trace_cmd(target, max_hops, timeout_ms, windows), max_hops * (3 * timeout_ms / 1000 + 1) + 10)
    hops = parse_tracert(trace_text)
    if not hops:
        raise ProbeError(f"could not read any hop from {tool} output")
    pings: dict = {}
    for h in hops:
        if h.host and valid_target(h.host) and h.host not in pings:     # only addresses the trace itself printed
            pings[h.host] = _run(ping_cmd(h.host, count, timeout_ms, windows), count * (timeout_ms / 1000 + 1) + 10)
    return build_capture(target, trace_text, pings)
