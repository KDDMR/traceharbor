FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRACEHARBOR_HOST=0.0.0.0 \
    TRACEHARBOR_PORT=8080 \
    TRACEHARBOR_DB=/data/traceharbor.db

WORKDIR /app
RUN useradd --create-home --uid 10001 traceharbor && mkdir /data && chown traceharbor:traceharbor /data

COPY --chown=traceharbor:traceharbor traceharbor ./traceharbor
COPY --chown=traceharbor:traceharbor traceharbor_sdk ./traceharbor_sdk

USER traceharbor
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/health', timeout=2)"]
CMD ["python", "-m", "traceharbor.server"]

