import os

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Points at the vLLM Service inside the cluster (its Kubernetes DNS
# name), not the external NodePort. Set per-environment via Helm values.
MODEL_API_URL = os.environ.get(
    "MODEL_API_URL", "http://localhost:8000/v1/chat/completions"
)
API_KEY = os.environ.get("API_KEY", "")
MODEL_NAME = os.environ.get("MODEL_NAME", "llama-3.2-3b-instruct")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


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

    reply = response.json()["choices"][0]["message"]["content"]
    return jsonify({"reply": reply})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
