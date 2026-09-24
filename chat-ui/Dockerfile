# Lightweight base since this app has no GPU work of its own,
# it just proxies chat requests to the model service.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Internal container port. The external NodePort (8001 staging, 8002
# production) is mapped to this by the Kubernetes Service, so this
# number doesn't need to match either of those.
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
