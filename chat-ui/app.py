import os
import time

import requests
from flask import Flask, Response, g, jsonify, render_template, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

app = Flask(__name__)

# Points at the vLLM Service inside the cluster (its Kubernetes DNS
# name), not the external NodePort. Set per-environment via Helm values.
MODEL_API_URL = os.environ.get(
    "MODEL_API_URL", "http://localhost:8000/v1/chat/completions"
)
API_KEY = os.environ.get("API_KEY", "")
MODEL_NAME = os.environ.get("MODEL_NAME", "llama-3.2-3b-instruct")

# Metrics for the /chat route only. The probes hit /health every few
# seconds and Prometheus hits /metrics, so counting those would bury the
# real traffic. Only numbers are recorded here, never what people type
# or what the model answers.
CHAT_REQUESTS = Counter(
    "chat_requests_total",
    "Chat requests handled, by HTTP status code.",
    ["status"],
)
# Buckets are sized for an LLM reply, which takes seconds, not
# milliseconds. The proxy gives up on the model after 60 seconds.
CHAT_DURATION = Histogram(
    "chat_request_duration_seconds",
    "Time from a chat request arriving to its reply going back, including the model call.",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 45, 60, 90),
)
CHAT_IN_FLIGHT = Gauge(
    "chat_requests_in_flight",
    "Chat requests being handled right now.",
)
CHAT_TOKENS = Counter(
    "chat_tokens_total",
    "Tokens reported by the model service, by type.",
    ["type"],
)

# Create the series up front so dashboards and rate() queries see a zero
# instead of a missing metric before the first request or the first error.
for _status in ("200", "400", "502"):
    CHAT_REQUESTS.labels(status=_status)
for _type in ("prompt", "completion"):
    CHAT_TOKENS.labels(type=_type)


@app.before_request
def start_chat_timer():
    if request.path == "/chat":
        g.chat_started = time.perf_counter()
        CHAT_IN_FLIGHT.inc()


@app.after_request
def record_chat_metrics(response):
    if "chat_started" in g:
        CHAT_REQUESTS.labels(status=str(response.status_code)).inc()
        CHAT_DURATION.observe(time.perf_counter() - g.chat_started)
    return response


# Runs even when the request blew up, so the in-flight gauge can't get
# stuck above zero.
@app.teardown_request
def finish_chat_request(_exc):
    if g.pop("chat_started", None) is not None:
        CHAT_IN_FLIGHT.dec()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"error": "no messages provided"}), 400

    try:
        response = requests.post(
            MODEL_API_URL,
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": MODEL_NAME,
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.7,
            },
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": f"Model service unreachable: {exc}"}), 502

    payload = response.json()

    # vLLM reports token counts in the reply. Tolerate a missing or odd
    # usage block rather than failing a chat over a metric.
    usage = payload.get("usage") or {}
    CHAT_TOKENS.labels(type="prompt").inc(int(usage.get("prompt_tokens") or 0))
    CHAT_TOKENS.labels(type="completion").inc(int(usage.get("completion_tokens") or 0))

    reply = payload["choices"][0]["message"]["content"]
    return jsonify({"reply": reply})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
