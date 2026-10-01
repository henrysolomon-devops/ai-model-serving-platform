# Lightweight base since this app has no GPU work of its own,
# it just proxies chat requests to the model service.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Not root. A number, so Kubernetes can check that it is not root.
USER 10001

# Internal container port. The external NodePort (8001 staging, 8002
# production) is mapped to this by the Kubernetes Service, so this
# number doesn't need to match either of those.
EXPOSE 5000
# One worker with several threads, not several workers. The proxy mostly
# waits on the model, so threads give plenty of concurrency, and every
# request lands in the same process. With two workers each one would keep
# its own metric counters and every scrape of /metrics would show only
# half the picture. The control socket is off, nothing uses it and it would
# need a home folder to write to.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--no-control-socket", "app:app"]
