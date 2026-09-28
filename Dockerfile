FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# SQLite lives here; mount a persistent volume/disk at /srv/data in production.
RUN mkdir -p /srv/data
ENV DATA_DIR=/srv/data

EXPOSE 8000

# Caddy terminates TLS and reverse-proxies over the internal docker network;
# uvicorn trusts X-Forwarded-Proto/For (SMA-543) so redirects built by the app
# (e.g. Starlette's trailing-slash redirect) use https://, not http://.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
