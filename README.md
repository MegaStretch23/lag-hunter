# lag-hunter

A command-line tool that traces the route to one host (a game server, say), pings every hop the trace printed, and prints a per-hop table of average and maximum latency and ping loss. It also marks a **heuristic suspect hop**: the first hop where latency or loss rises and the later hops stay up there.

Python 3.9+, standard library only, MIT. It runs the system `tracert` and `ping` on Windows, and `traceroute` and `ping` on other systems.

## Quickstart

```sh
git clone https://github.com/MegaStretch23/lag-hunter && cd lag-hunter
python -m lag_hunter --target <host> --count 20
```

(`python3` on Linux and macOS, which also need `traceroute` installed.) `--save capture.txt` keeps the raw tool output of that run; `--from-file capture.txt` re-reads it later with no network access. Or install the `lag-hunter` command with `pip install .`.

What it sends: one trace to the target you name, then `--count` pings to each address that trace printed. Nothing else, no port or host scanning.

## What the output means

- **avg ms / max ms**: over the ping replies received from that hop. `<1 ms` replies are counted as 0.5 ms. If a hop was not pinged, the numbers come from the three trace probes and the loss column shows `-`.
- **loss %**: pings sent minus replies received, over pings sent. A reply such as "Destination host unreachable" is not counted as a reply.
- **heuristic suspect hop**: the first hop whose average latency is at least `--lat-jump` ms (default 20) above the previous hop with data, or whose loss is at least `--loss-jump` points (default 5) above it, **and** every later hop stays at least half that rise above the previous level. A single spike that later hops do not share is not marked. A hop that never answers pings while later hops do is ignored. The first hop is compared with 0.
- It is a heuristic on `--count` pings per hop, not a root cause. Routers often de-prioritise ICMP, so a hop can look slow or lossy while forwarding traffic fine.

Other options: `--json`, `--timeout-ms`, `--max-hops`, `--lat-jump`, `--loss-jump`.

## Saved sample runs

The input for these runs is **synthetic**: `tests/make_fixture.py` (seed 11) writes Windows-format `tracert` and `ping` text for made-up documentation addresses, with a latency jump after hop 3 in one file and a loss jump at hop 3 in the other. They are not measurements of any real network. The tables are the program's output, saved in `samples/`.

```
# SYNTHETIC input (tests/make_fixture.py, random.seed(11)); not a real network run
# command: python3 -m lag_hunter --from-file tests/fixtures/capture_latency_jump_SYNTHETIC.txt
lag-hunter  target game.example.net

hop  host                           avg ms   max ms  loss %  note
  1  192.168.1.1                       0.7      1.0       0
  2  10.20.0.1                         8.5     10.0       0
  3  198.51.100.1                      8.9     11.0       0
  4  *                                   -        -       -  no reply to the trace
  5  198.51.100.77                    59.0     61.0       0  <-- heuristic suspect hop
  6  203.0.113.9                      60.0     63.0       0
  7  203.0.113.50                     59.8     63.0       0

Heuristic suspect hop: 5 (198.51.100.77): average latency rises from 8.9 ms to 59.0 ms and stays up.
This is a heuristic on a few pings per hop, not a diagnosis. A router that de-prioritises ICMP can look slow or lossy while forwarding fine.
```

```
# SYNTHETIC input (tests/make_fixture.py, random.seed(11)); not a real network run
# command: python3 -m lag_hunter --from-file tests/fixtures/capture_loss_jump_SYNTHETIC.txt
lag-hunter  target game.example.net

hop  host                           avg ms   max ms  loss %  note
  1  192.168.1.1                       0.7      1.0       0
  2  10.20.0.1                         8.1      9.0       0
  3  198.51.100.1                     10.0     11.0      30  <-- heuristic suspect hop
  4  *                                   -        -       -  no reply to the trace
  5  198.51.100.77                    12.0     14.0      40
  6  203.0.113.9                      12.0     13.0      30
  7  203.0.113.50                     14.1     16.0      30

Heuristic suspect hop: 3 (198.51.100.1): ping loss rises from 0% to 30% and stays up.
This is a heuristic on a few pings per hop, not a diagnosis. A router that de-prioritises ICMP can look slow or lossy while forwarding fine.
```

## Tests

```sh
python -m unittest discover -s tests
```

32 tests, no network. What they check:

- Parsing of Windows `tracert` and `ping` text (`<1 ms`, timeouts, `name [ip]` lines, "Destination host unreachable" not counted as a reply) and of Linux `traceroute` hop lines.
- One real capture: `tests/fixtures/ping_linux_1.1.1.1_REAL.txt` is unmodified output of `ping -c 20 -i 0.2 1.1.1.1` (Linux, 2026-11-13); the parsed min, avg and max are compared with the `rtt min/avg/max` line `ping` printed itself.
- The suspect-hop rule on hand-built data: a jump that stays, a transient spike, a rate-limited middle hop, a path that dies, thresholds.
- CLI argument errors, including rejected target strings such as `-n 5` or `x;rm`, and `--from-file` output.
- With `subprocess` replaced by a stub: the exact `tracert`/`ping` command lines, and that only the addresses the trace printed are pinged.

**Not tested:** I had no real Windows `tracert` capture, so the Windows `tracert` and `ping` fixtures (`*_SYNTHETIC.txt`) are written by hand from the documented output layout. They show the parser reads that layout; they do not show that every Windows version prints it identically. The live `tracert`/`traceroute` runs are not exercised by the tests.

## Limits

- Ping loss to a router measures that router's ICMP handling as well as the path.
- Per-hop numbers come from `--count` pings (default 20) taken one hop after another, not at the same moment.
- IPv4 text output was the target; IPv6 output is not tested.

## Also by the author

If you need data pipelines rather than a lag tool, I run pay-per-event tools on Apify, for example the [SEC Form 4 insider cluster scanner](https://apify.com/johnveds15/sec-form4-insider-clusters): $0.0004 per Form 4 filing parsed and $0.02 per insider cluster detected (prices read from the Apify API on 2026-11-13). Source-code packs are on [Gumroad](https://vedovino.gumroad.com/l/xrrtln), for example the Browser Frame-Interpolation and Upscaling Toolkit (source code), $9. Neither is related to lag-hunter; there is no paid version of it.

MIT licensed.
