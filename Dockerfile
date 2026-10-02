FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY dispatch/ dispatch/
COPY planstate/ planstate/
RUN pip install --no-cache-dir .

ENV DISPATCH_DB=/data/dispatch.db
ENV DISPATCH_CLIENT=hermes
ENV DISPATCH_EVAL_MINUTES=0

VOLUME /data
EXPOSE 8082

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8082/health')"

CMD ["dispatch", "serve", "--http", "--port", "8082", "--api"]
