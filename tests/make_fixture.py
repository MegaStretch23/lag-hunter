"""Generates the SYNTHETIC capture fixtures (random.seed(11)); they are NOT real network runs.
Usage: python3 tests/make_fixture.py   (rewrites tests/fixtures/capture_*_SYNTHETIC.txt)"""
import random, pathlib

HERE = pathlib.Path(__file__).parent
TRACE = (pathlib.Path(HERE / "fixtures" / "tracert_windows_SYNTHETIC.txt")).read_text()


def win_ping(host, base, spread, lost_idx, n=10):
    lines = ["", f"Pinging {host} with 32 bytes of data:"]
    got = []
    for i in range(n):
        if i in lost_idx:
            lines.append("Request timed out."); continue
        t = max(0, round(base + random.uniform(-spread, spread)))
        got.append(t)
        lines.append(f"Reply from {host}: bytes=32 time={t}ms TTL=60" if t >= 1 else f"Reply from {host}: bytes=32 time<1ms TTL=60")
    lines += ["", f"Ping statistics for {host}:", f"    Packets: Sent = {n}, Received = {len(got)}, Lost = {n - len(got)} ({100 * (n - len(got)) // n}% loss),"]
    if got:
        lines += ["Approximate round trip times in milli-seconds:", f"    Minimum = {min(got)}ms, Maximum = {max(got)}ms, Average = {round(sum(got) / len(got))}ms"]
    return "\n".join(lines)


def capture(profile):
    out = ["=== tracert game.example.net ===", TRACE.rstrip("\n")]
    for host, base, spread, lost in profile:
        out += [f"=== ping {host} ===", win_ping(host, base, spread, lost)]
    return "\n".join(out) + "\n"


random.seed(11)
LATENCY = [("192.168.1.1", 0.4, 0.4, set()), ("10.20.0.1", 8.5, 1.5, set()), ("198.51.100.1", 9.5, 1.5, set()),
           ("198.51.100.77", 58, 3, set()), ("203.0.113.9", 60, 3, set()), ("203.0.113.50", 60, 3, set())]
LOSS = [("192.168.1.1", 0.4, 0.4, set()), ("10.20.0.1", 8.5, 1.5, set()), ("198.51.100.1", 9.5, 1.5, {2, 7, 8}),
        ("198.51.100.77", 12, 2, {1, 4, 6, 9}), ("203.0.113.9", 13, 2, {0, 3, 5}), ("203.0.113.50", 14, 2, {2, 6, 8})]
(HERE / "fixtures" / "capture_latency_jump_SYNTHETIC.txt").write_text(capture(LATENCY))
(HERE / "fixtures" / "capture_loss_jump_SYNTHETIC.txt").write_text(capture(LOSS))
