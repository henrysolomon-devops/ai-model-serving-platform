#!/usr/bin/env python3
"""Compares the canary with production before it gets more traffic.

It needs kubectl pointed at the cluster, and the gateway reachable on its
node port. Run it through canary-check.sh. The exit code is 0 when the canary
looks healthy and 1 when it does not.
"""
import http.client
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

GATEWAY_PORT = 8003
NAMESPACE = "production"
STABLE = "model-service-predictor"
CANARY = "model-service-canary-predictor"

# KServe routes each model on its own host name. The route host is the one
# the chat UI uses, and it is the one that splits traffic by weight.
STABLE_HOST = "model-service-production.example.com"
CANARY_HOST = "model-service-canary-production.example.com"
ROUTE_HOST = "model-service.production.svc.cluster.local"

PROMETHEUS = "/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:http-web/proxy"

PROMPTS = [
    "Say hello in one short sentence.",
    "Name one color.",
    "What is 2 plus 2?",
    "Give me one word for happy.",
    "Name a fruit.",
]
# Each model gets this many rounds of the prompts above, one request at a time.
AB_ROUNDS = 4
# Requests sent through the weighted route to measure the traffic split.
BATCH_SIZE = 300
BATCH_WORKERS = 8
# How long to wait for Prometheus to catch up, and how often to look.
SCRAPE_TIMEOUT = 180
SCRAPE_INTERVAL = 10

# These limits are starting points. Adjust them once there are real numbers.
MAX_ERROR_POINTS = 2.0
LATENCY_RATIO = 1.3
LATENCY_SLACK = 0.3
MAX_QUEUE = 5
MAX_KV_CACHE = 0.9
MAX_GPU_TEMP = 85
MIN_GPU_MIB = 8000


def percentile(values, pct):
    """Nearest-rank percentile, or None when there are no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def share_ok(canary_count, total_count, weight):
    """True when the canary's share of requests fits its weight within 3 sigma."""
    p = weight / 100
    expected = total_count * p
    tolerance = 3 * math.sqrt(total_count * p * (1 - p))
    return abs(canary_count - expected) <= tolerance


class Cluster:
    """Everything that touches the outside world, so tests can swap it out."""

    def __init__(self, ip, api_key, port=GATEWAY_PORT):
        self.ip = ip
        self.api_key = api_key
        self.port = port

    def send(self, host, prompt, max_tokens=16):
        """Sends one prompt through the gateway. Returns (ok, seconds)."""
        body = json.dumps({
            "model": "llama-3.2-3b-instruct",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }).encode()
        request = urllib.request.Request(
            f"http://{self.ip}:{self.port}/v1/chat/completions",
            data=body,
            method="POST",
            headers={
                "Host": host,
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                text = json.load(response)["choices"][0]["message"]["content"]
            ok = bool(text and text.strip())
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, KeyError, IndexError):
            ok = False
        return ok, time.monotonic() - start

    def route_weights(self):
        """The backend weights of the production route, by Service name."""
        result = subprocess.run(
            ["kubectl", "get", "httproute", "model-service", "-n", NAMESPACE, "-o", "json"],
            capture_output=True, text=True, check=True,
        )
        refs = json.loads(result.stdout)["spec"]["rules"][0]["backendRefs"]
        return {ref["name"]: ref.get("weight", 1) for ref in refs}

    def prom(self, expr):
        """First value of an instant query, or None when there is none."""
        path = f"{PROMETHEUS}/api/v1/query?query={urllib.parse.quote(expr)}"
        result = subprocess.run(["kubectl", "get", "--raw", path], capture_output=True, text=True)
        if result.returncode != 0:
            return None
        try:
            samples = json.loads(result.stdout)["data"]["result"]
            value = float(samples[0]["value"][1])
        except (ValueError, KeyError, IndexError):
            return None
        return None if math.isnan(value) or math.isinf(value) else value

    def sleep(self, seconds):
        time.sleep(seconds)


def wait_until(cluster, check, timeout=SCRAPE_TIMEOUT, interval=SCRAPE_INTERVAL):
    """Calls check until it returns something truthy. None if time runs out."""
    waited = 0
    while True:
        value = check()
        if value:
            return value
        if waited >= timeout:
            return None
        cluster.sleep(interval)
        waited += interval


def success_counts(cluster):
    """Requests each model has finished so far, as Prometheus sees them."""
    counts = {}
    for name in (STABLE, CANARY):
        expr = f'sum(vllm:request_success_total{{namespace="{NAMESPACE}", deployment="{name}"}}) or vector(0)'
        counts[name] = cluster.prom(expr)
    if any(value is None for value in counts.values()):
        return None
    return counts


def row(check, production, canary, limit, ok):
    return {"check": check, "production": production, "canary": canary, "limit": limit, "ok": ok}


def error_rate(results):
    failed = sum(1 for ok, _ in results if not ok)
    return 100 * failed / len(results) if results else 0.0


def seconds(value):
    return "n/a" if value is None else f"{value:.2f} s"


# Each check is a name, a query for one model, how to print the value, the
# limit as text, and a test the canary's value has to pass.
METRIC_CHECKS = [
    (
        "Queue length, highest in 10 min",
        'max(max_over_time(vllm:num_requests_waiting{{namespace="{ns}", deployment="{d}"}}[10m]))',
        lambda v: f"{v:.0f}", f"under {MAX_QUEUE}", lambda v: v < MAX_QUEUE,
    ),
    (
        "KV cache use, highest in 10 min",
        'max(max_over_time(vllm:kv_cache_usage_perc{{namespace="{ns}", deployment="{d}"}}[10m]))',
        lambda v: f"{v * 100:.0f}%", f"under {MAX_KV_CACHE * 100:.0f}%", lambda v: v < MAX_KV_CACHE,
    ),
    (
        "GPU temperature, highest in 10 min",
        'max(max_over_time(DCGM_FI_DEV_GPU_TEMP{{namespace="{ns}", pod=~"{d}-.*"}}[10m]))',
        lambda v: f"{v:.0f} C", f"under {MAX_GPU_TEMP} C", lambda v: v < MAX_GPU_TEMP,
    ),
    (
        "GPU memory in use",
        'max(DCGM_FI_DEV_FB_USED{{namespace="{ns}", pod=~"{d}-.*"}})',
        lambda v: f"{v:.0f} MiB", f"over {MIN_GPU_MIB} MiB", lambda v: v > MIN_GPU_MIB,
    ),
    (
        "Container restarts",
        'sum(kube_pod_container_status_restarts_total{{namespace="{ns}", pod=~"{d}-.*"}})',
        lambda v: f"{v:.0f}", "none", lambda v: v == 0,
    ),
]


def run_check(cluster, weight, ab_rounds=AB_ROUNDS, batch_size=BATCH_SIZE, log=print):
    """Runs every check and returns the list of rows."""
    rows = []

    log("Checking the route weights...")
    weights = cluster.route_weights()
    expected = {STABLE: 100 - weight, CANARY: weight}
    actual = {name: weights.get(name) for name in expected}
    rows.append(row(
        "Route weights, stable and canary",
        str(actual[STABLE]), str(actual[CANARY]),
        f"{expected[STABLE]} and {expected[CANARY]}", actual == expected,
    ))
    if actual != expected:
        log("The route does not have the expected weights yet, so nothing else is checked.")
        return rows

    before = success_counts(cluster)

    log(f"Sending {ab_rounds * len(PROMPTS)} prompts to each model directly...")
    stable_results, canary_results = [], []
    for _ in range(ab_rounds):
        for prompt in PROMPTS:
            stable_results.append(cluster.send(STABLE_HOST, prompt))
            canary_results.append(cluster.send(CANARY_HOST, prompt))

    stable_errors, canary_errors = error_rate(stable_results), error_rate(canary_results)
    rows.append(row(
        "Error rate, direct requests",
        f"{stable_errors:.1f}%", f"{canary_errors:.1f}%",
        f"at most {MAX_ERROR_POINTS:.0f} points above production",
        canary_errors <= stable_errors + MAX_ERROR_POINTS,
    ))
    stable_times = [t for ok, t in stable_results if ok]
    canary_times = [t for ok, t in canary_results if ok]
    stable_p95, canary_p95 = percentile(stable_times, 95), percentile(canary_times, 95)
    latency_ok = (
        stable_p95 is not None and canary_p95 is not None
        and canary_p95 <= max(stable_p95 * LATENCY_RATIO, stable_p95 + LATENCY_SLACK)
    )
    rows.append(row(
        "Response time p95, direct requests",
        seconds(stable_p95), seconds(canary_p95),
        f"at most {LATENCY_RATIO}x production", latency_ok,
    ))

    # Prometheus has to see these requests before the split can be measured.
    stable_ok = sum(1 for ok, _ in stable_results if ok)
    canary_ok = sum(1 for ok, _ in canary_results if ok)

    def caught_up_with_direct():
        now = success_counts(cluster)
        if now is None or before is None:
            return None
        if now[STABLE] - before[STABLE] >= stable_ok and now[CANARY] - before[CANARY] >= canary_ok:
            return now
        return None

    log("Waiting for Prometheus to see them...")
    base = wait_until(cluster, caught_up_with_direct)
    if base is None:
        rows.append(row("Prometheus caught up with the direct requests", "-", "-", "within 3 min", False))
        return rows

    log(f"Sending {batch_size} prompts through the weighted route...")
    prompts = [PROMPTS[i % len(PROMPTS)] for i in range(batch_size)]
    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
        batch = list(pool.map(lambda p: cluster.send(ROUTE_HOST, p, max_tokens=8), prompts))
    batch_errors = error_rate(batch)
    batch_ok = sum(1 for ok, _ in batch if ok)
    rows.append(row(
        "Error rate, through the route",
        "-", f"{batch_errors:.1f}%",
        f"at most {MAX_ERROR_POINTS:.0f} points above production's direct rate",
        batch_errors <= stable_errors + MAX_ERROR_POINTS,
    ))

    def caught_up_with_batch():
        now = success_counts(cluster)
        if now is None:
            return None
        if (now[STABLE] - base[STABLE]) + (now[CANARY] - base[CANARY]) >= batch_ok:
            return now
        return None

    log("Waiting for Prometheus to see them...")
    after = wait_until(cluster, caught_up_with_batch)
    if after is None:
        rows.append(row("Prometheus caught up with the batch", "-", "-", "within 3 min", False))
        return rows

    stable_got = after[STABLE] - base[STABLE]
    canary_got = after[CANARY] - base[CANARY]
    total = stable_got + canary_got
    tolerance = 3 * math.sqrt(total * (weight / 100) * (1 - weight / 100))
    canary_pct = 100 * canary_got / total if total else 0.0
    rows.append(row(
        "Traffic split, requests served",
        f"{stable_got:.0f}", f"{canary_got:.0f} ({canary_pct:.0f}%)",
        f"{total * weight / 100:.0f} plus or minus {tolerance:.0f} for the canary",
        share_ok(canary_got, total, weight),
    ))

    log("Reading the metrics...")
    for name, template, show, limit, passes in METRIC_CHECKS:
        values = {}
        for label, deployment in (("production", STABLE), ("canary", CANARY)):
            values[label] = cluster.prom(template.format(ns=NAMESPACE, d=deployment))
        canary_value = values["canary"]
        rows.append(row(
            name,
            "n/a" if values["production"] is None else show(values["production"]),
            "no data" if canary_value is None else show(canary_value),
            limit,
            canary_value is not None and passes(canary_value),
        ))
    return rows


def render_report(weight, rows):
    """A markdown table, ready to post as a comment."""
    lines = [
        f"### Canary check at {weight}% traffic",
        "",
        "| Check | Production | Canary | Limit | Result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(f"| {r['check']} | {r['production']} | {r['canary']} | {r['limit']} | {'pass' if r['ok'] else 'FAIL'} |")
    verdict = "PASS" if all(r["ok"] for r in rows) else "FAIL"
    lines += ["", f"**Result: {verdict}**", ""]
    return "\n".join(lines)


def main(argv):
    if len(argv) != 4:
        print("Usage: canary_check.py <weight 0-100> <server-ip> <api-key>", file=sys.stderr)
        return 2
    try:
        weight = int(argv[1])
    except ValueError:
        weight = -1
    if not 0 <= weight <= 100:
        print("The weight must be a whole number from 0 to 100.", file=sys.stderr)
        return 2

    cluster = Cluster(argv[2], argv[3])
    rows = run_check(cluster, weight, log=lambda text: print(text, flush=True))
    report = render_report(weight, rows)
    print()
    print(report)
    with open(os.environ.get("CANARY_REPORT", "canary-report.md"), "w") as handle:
        handle.write(report)
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
