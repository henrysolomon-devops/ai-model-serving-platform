import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import canary_check as cc


class FakeCluster:
    """A cluster that answers like a healthy one unless a test says otherwise."""

    def __init__(self, weight, canary_ok=True, canary_slow=1.0, lag=False,
                 actual_share=None, canary_restarts=0, route=None):
        self.weights = route or {cc.STABLE: 100 - weight, cc.CANARY: weight}
        self.canary_ok = canary_ok
        self.canary_slow = canary_slow
        self.lag = lag
        self.actual_share = weight / 100 if actual_share is None else actual_share
        self.canary_restarts = canary_restarts
        self.counts = {cc.STABLE: 0, cc.CANARY: 0}
        self.routed = 0
        self.lock = threading.Lock()

    def send(self, host, prompt, max_tokens=16):
        with self.lock:
            if host == cc.STABLE_HOST:
                target = cc.STABLE
            elif host == cc.CANARY_HOST:
                target = cc.CANARY
            else:
                self.routed += 1
                crossed = int(self.routed * self.actual_share) > int((self.routed - 1) * self.actual_share)
                target = cc.CANARY if crossed else cc.STABLE
            if target == cc.CANARY and not self.canary_ok:
                return False, 0.1
            self.counts[target] += 1
        return True, 1.0 * (self.canary_slow if target == cc.CANARY else 1.0)

    def route_weights(self):
        return self.weights

    def prom(self, expr):
        name = cc.CANARY if cc.CANARY in expr else cc.STABLE
        if "vllm:request_success_total" in expr:
            return 0.0 if self.lag else float(self.counts[name])
        if "num_requests_waiting" in expr:
            return 0.0
        if "kv_cache_usage_perc" in expr:
            return 0.3
        if "GPU_TEMP" in expr:
            return 61.0
        if "FB_USED" in expr:
            return 13500.0
        if "restarts_total" in expr:
            return float(self.canary_restarts) if name == cc.CANARY else 0.0
        return None

    def sleep(self, seconds):
        pass


def run(cluster, weight):
    return cc.run_check(cluster, weight, log=lambda text: None)


def failed(rows):
    return [r["check"] for r in rows if not r["ok"]]


def test_percentile_picks_the_nearest_rank():
    assert cc.percentile([], 95) is None
    assert cc.percentile([5], 95) == 5
    assert cc.percentile(list(range(1, 21)), 95) == 19
    assert cc.percentile([3, 1, 2], 50) == 2


@pytest.mark.parametrize("canary, total, weight, expected", [
    (60, 300, 20, True),
    (80, 300, 20, True),
    (82, 300, 20, False),
    (0, 300, 0, True),
    (1, 300, 0, False),
    (300, 300, 100, True),
    (299, 300, 100, False),
])
def test_share_must_fit_the_weight(canary, total, weight, expected):
    assert cc.share_ok(canary, total, weight) is expected


@pytest.mark.parametrize("weight", [0, 10, 50, 100])
def test_a_healthy_canary_passes_at_every_weight(weight):
    assert failed(run(FakeCluster(weight), weight)) == []


def test_a_canary_that_errors_fails():
    rows = run(FakeCluster(20, canary_ok=False), 20)
    assert "Error rate, direct requests" in failed(rows)
    assert "Error rate, through the route" in failed(rows)


def test_a_slow_canary_fails_on_response_time():
    rows = run(FakeCluster(20, canary_slow=3.0), 20)
    assert failed(rows) == ["Response time p95, direct requests"]


def test_a_canary_that_restarted_fails():
    rows = run(FakeCluster(20, canary_restarts=1), 20)
    assert failed(rows) == ["Container restarts"]


def test_traffic_that_does_not_follow_the_weight_fails():
    # The route says 0 but the canary still gets one request in five.
    rows = run(FakeCluster(0, actual_share=0.2), 0)
    assert failed(rows) == ["Traffic split, requests served"]


def test_wrong_route_weights_stop_the_check_early():
    cluster = FakeCluster(20, route={cc.STABLE: 100, cc.CANARY: 0})
    rows = run(cluster, 20)
    assert failed(rows) == ["Route weights, stable and canary"]
    assert len(rows) == 1
    assert cluster.counts == {cc.STABLE: 0, cc.CANARY: 0}


def test_missing_prometheus_data_fails_instead_of_hanging():
    rows = run(FakeCluster(20, lag=True), 20)
    assert failed(rows) == ["Prometheus caught up with the direct requests"]


def test_the_report_is_a_table_with_a_verdict():
    good = cc.render_report(20, run(FakeCluster(20), 20))
    assert good.startswith("### Canary check at 20% traffic")
    assert "| Check | Production | Canary | Limit | Result |" in good
    assert "**Result: PASS**" in good

    bad = cc.render_report(20, run(FakeCluster(20, canary_restarts=2), 20))
    assert "| Container restarts | 0 | 2 | none | FAIL |" in bad
    assert "**Result: FAIL**" in bad


# ---- the real HTTP call, against a small local server ----


@pytest.fixture
def gateway():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.headers["Host"], self.headers["Authorization"], body))
            if self.headers["Host"] == "broken.example.com":
                self.send_response(500)
                self.end_headers()
                return
            payload = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], seen
    server.shutdown()


def test_send_sets_the_host_and_the_key(gateway):
    port, seen = gateway
    ok, took = cc.Cluster("127.0.0.1", "secret", port=port).send("model.example.com", "Name a fruit.")
    assert ok is True and took >= 0
    host, auth, body = seen[0]
    assert host == "model.example.com"
    assert auth == "Bearer secret"
    assert body["messages"][0]["content"] == "Name a fruit."
    assert body["temperature"] == 0


def test_send_reports_a_server_error_as_not_ok(gateway):
    port, _ = gateway
    ok, _ = cc.Cluster("127.0.0.1", "secret", port=port).send("broken.example.com", "hi")
    assert ok is False


def test_send_reports_an_unreachable_gateway_as_not_ok():
    ok, _ = cc.Cluster("127.0.0.1", "secret", port=1).send("model.example.com", "hi")
    assert ok is False


def test_main_rejects_a_bad_weight():
    assert cc.main(["canary_check.py", "150", "1.2.3.4", "key"]) == 2
    assert cc.main(["canary_check.py", "abc", "1.2.3.4", "key"]) == 2
    assert cc.main(["canary_check.py"]) == 2
