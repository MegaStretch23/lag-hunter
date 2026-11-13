import contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lag_hunter import probe as P
from lag_hunter.report import Row, analyse, find_suspect, render
from lag_hunter.cli import main

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def fx(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def row(n, avg, loss=0.0, recv=10, sent=10):
    return Row(n, f"10.0.0.{n}", avg, avg, loss, sent, recv, "ping")


class ParseTests(unittest.TestCase):
    def test_tracert_windows(self):
        hops = P.parse_tracert(fx("tracert_windows_SYNTHETIC.txt"))
        self.assertEqual([h.n for h in hops], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(hops[0].host, "192.168.1.1"); self.assertEqual(hops[0].rtts, [0.5, 0.5, 0.5])
        self.assertEqual(hops[1].rtts, [8.0, 9.0, 8.0])
        self.assertIsNone(hops[3].host); self.assertEqual(hops[3].rtts, [])
        self.assertEqual(hops[6].host, "203.0.113.50")       # name [ip] -> the address in brackets

    def test_tracert_linux_lines(self):
        txt = "traceroute to x (203.0.113.5), 30 hops max\n 1  192.168.1.1  0.511 ms  0.4 ms  0.45 ms\n 2  * * *\n 3  10.1.1.1  12.5 ms  *  13.1 ms\n"
        hops = P.parse_tracert(txt)
        self.assertEqual([(h.n, h.host, len(h.rtts)) for h in hops], [(1, "192.168.1.1", 3), (2, None, 0), (3, "10.1.1.1", 2)])

    def test_ping_real_linux_matches_its_own_summary(self):
        txt = fx("ping_linux_1.1.1.1_REAL.txt")
        r = P.parse_ping(txt)
        self.assertEqual((r.sent, r.received), (20, 20))
        self.assertAlmostEqual(min(r.rtts), 1.315, delta=0.01); self.assertAlmostEqual(max(r.rtts), 1.870, delta=0.01)
        self.assertAlmostEqual(sum(r.rtts) / len(r.rtts), 1.441, delta=0.01)    # "rtt min/avg/max/mdev = 1.315/1.441/1.870/0.118 ms"

    def test_ping_windows_counts_unreachable_as_lost(self):
        r = P.parse_ping(fx("ping_windows_SYNTHETIC.txt"))
        self.assertEqual((r.sent, r.received), (5, 3)); self.assertEqual(r.rtts, [9.0, 10.0, 0.5])

    def test_ping_without_summary(self):
        r = P.parse_ping("Reply from 1.2.3.4: bytes=32 time=5ms TTL=1\nRequest timed out.\n")
        self.assertEqual((r.sent, r.received), (2, 1))

    def test_capture_roundtrip(self):
        t, trace, pings = P.parse_capture(fx("capture_latency_jump_SYNTHETIC.txt"))
        self.assertEqual(t, "game.example.net"); self.assertEqual(len(pings), 6)
        t2, trace2, pings2 = P.parse_capture(P.build_capture(t, trace, pings))
        self.assertEqual((t, len(pings)), (t2, len(pings2)))

    def test_capture_without_trace_section(self):
        with self.assertRaises(P.ProbeError):
            P.parse_capture("=== ping 1.1.1.1 ===\nx\n")


class SuspectTests(unittest.TestCase):
    def test_latency_jump_that_stays(self):
        rows = [row(1, 1), row(2, 9), row(3, 10), row(4, 60), row(5, 61), row(6, 62)]
        s = find_suspect(rows)
        self.assertEqual(s["hop"], 4); self.assertIn("rises from 10.0 ms to 60.0 ms", s["reason"])

    def test_transient_spike_is_not_suspect(self):
        rows = [row(1, 1), row(2, 9), row(3, 80), row(4, 11), row(5, 12)]
        self.assertIsNone(find_suspect(rows))

    def test_loss_jump_that_stays(self):
        rows = [row(1, 1), row(2, 9), row(3, 10, loss=20, recv=8), row(4, 11, loss=30, recv=7), row(5, 12, loss=20, recv=8)]
        s = find_suspect(rows)
        self.assertEqual(s["hop"], 3); self.assertIn("loss rises from 0% to 20%", s["reason"])

    def test_icmp_rate_limited_middle_hop_ignored(self):
        rows = [row(1, 1), row(2, 9, loss=60, recv=4), row(3, 10), row(4, 11), row(5, 12)]
        self.assertIsNone(find_suspect(rows))

    def test_hop_that_never_answers_with_later_hops_answering_is_ignored(self):
        rows = [row(1, 1), Row(2, "10.0.0.2", None, None, 100.0, 10, 0, "ping"), row(3, 10), row(4, 11)]
        self.assertIsNone(find_suspect(rows))

    def test_path_that_dies(self):
        rows = [row(1, 1), row(2, 9), Row(3, "10.0.0.3", None, None, 100.0, 10, 0, "ping"), Row(4, "10.0.0.4", None, None, 100.0, 10, 0, "ping")]
        self.assertEqual(find_suspect(rows)["hop"], 3)

    def test_first_hop_is_judged_against_zero(self):
        self.assertEqual(find_suspect([row(1, 45), row(2, 46), row(3, 47)])["hop"], 1)

    def test_thresholds_are_parameters(self):
        rows = [row(1, 1), row(2, 9), row(3, 25), row(4, 26)]
        self.assertIsNone(find_suspect(rows)); self.assertEqual(find_suspect(rows, lat_jump=10)["hop"], 3)

    def test_no_rows(self):
        self.assertIsNone(find_suspect([]))


class FixtureRunTests(unittest.TestCase):
    def test_latency_fixture(self):
        target, rows, s = analyse(fx("capture_latency_jump_SYNTHETIC.txt"), 20, 5)
        self.assertEqual(target, "game.example.net"); self.assertEqual(len(rows), 7)
        self.assertEqual(rows[3].source, "none")
        self.assertEqual(s["hop"], 5); self.assertEqual(s["host"], "198.51.100.77")
        self.assertIn("<-- heuristic suspect hop", render(target, rows, s, 20, 5))

    def test_loss_fixture(self):
        _, rows, s = analyse(fx("capture_loss_jump_SYNTHETIC.txt"), 20, 5)
        self.assertEqual(s["hop"], 3); self.assertIn("loss", s["reason"])

    def test_deterministic(self):
        a = render(*analyse(fx("capture_latency_jump_SYNTHETIC.txt"), 20, 5), 20, 5)
        b = render(*analyse(fx("capture_latency_jump_SYNTHETIC.txt"), 20, 5), 20, 5)
        self.assertEqual(a, b)


def run_cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(args)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    path = os.path.join(FX, "capture_latency_jump_SYNTHETIC.txt")

    def test_from_file(self):
        code, out, _ = run_cli(["--from-file", self.path])
        self.assertEqual(code, 0); self.assertIn("Heuristic suspect hop: 5 (198.51.100.77)", out)

    def test_json(self):
        code, out, _ = run_cli(["--from-file", self.path, "--json"])
        self.assertEqual(code, 0); self.assertEqual(json.loads(out)["suspect"]["hop"], 5)

    def test_no_arguments(self):
        code, _, err = run_cli([]); self.assertEqual(code, 2); self.assertIn("--target is required", err)

    def test_both_target_and_file(self):
        self.assertEqual(run_cli(["--target", "x.example", "--from-file", self.path])[0], 2)

    def test_bad_target_rejected(self):
        for bad in ("-n 5", "a b", "x;rm", "$(id)", ""):
            self.assertEqual(run_cli(["--target", bad])[0], 2, bad)

    def test_bad_numbers(self):
        for args in (["--count", "0"], ["--count", "501"], ["--max-hops", "0"], ["--timeout-ms", "5"], ["--lat-jump", "0"]):
            self.assertEqual(run_cli(["--target", "x.example", *args])[0], 2, args)

    def test_missing_file(self):
        code, _, err = run_cli(["--from-file", "/nonexistent/capture.txt"]); self.assertEqual(code, 1); self.assertIn("lag_hunter:", err)

    def test_save_with_from_file_rejected(self):
        self.assertEqual(run_cli(["--from-file", self.path, "--save", "x.txt"])[0], 2)


class ProbeCommandTests(unittest.TestCase):
    def test_windows_commands(self):
        self.assertEqual(P.trace_cmd("h.example", 30, 1000, True), ["tracert", "-d", "-h", "30", "-w", "1000", "h.example"])
        self.assertEqual(P.ping_cmd("1.2.3.4", 20, 1000, True), ["ping", "-n", "20", "-w", "1000", "1.2.3.4"])

    def test_other_os_commands(self):
        self.assertEqual(P.ping_cmd("1.2.3.4", 5, 2000, False), ["ping", "-c", "5", "-W", "2", "1.2.3.4"])
        self.assertEqual(P.trace_cmd("h.example", 20, 1000, False)[0], "traceroute")

    def test_probe_pings_only_hops_the_trace_printed(self):
        calls = []

        def fake(cmd, timeout):
            calls.append(cmd)
            return fx("tracert_windows_SYNTHETIC.txt") if cmd[0] == "tracert" else fx("ping_windows_SYNTHETIC.txt")
        with mock.patch.object(P, "_run", fake):
            cap = P.probe("game.example.net", count=7, windows=True)
        pinged = [c[-1] for c in calls if c[0] == "ping"]
        self.assertEqual(pinged, ["192.168.1.1", "10.20.0.1", "198.51.100.1", "198.51.100.77", "203.0.113.9", "203.0.113.50"])
        self.assertEqual(calls[0][-1], "game.example.net"); self.assertTrue(all(c[2] == "7" for c in calls if c[0] == "ping"))
        self.assertEqual(P.parse_capture(cap)[0], "game.example.net")

    def test_probe_rejects_bad_target(self):
        with self.assertRaises(P.ProbeError):
            P.probe("--help", windows=True)

    def test_live_save_roundtrip(self):
        with mock.patch.object(P, "_run", lambda cmd, t: fx("tracert_windows_SYNTHETIC.txt") if cmd[0] == "tracert" else fx("ping_windows_SYNTHETIC.txt")):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "cap.txt")
                with mock.patch.object(P, "shutil") as sh, mock.patch("sys.platform", "win32"):
                    code, out, _ = run_cli(["--target", "game.example.net", "--save", p, "--count", "5"])
                self.assertEqual(code, 0); self.assertTrue(os.path.getsize(p) > 0); self.assertIn("lag-hunter  target game.example.net", out)


if __name__ == "__main__":
    unittest.main()
