# Local-build adapter for gpt-engineer. The upstream repo lives at
# AntonOsika/gpt-engineer; ships a `gpte` CLI but only via pip console_scripts,
# not as a docker image. We install from PyPI and drive it through a small
# one-shot wrapper that writes the task to a project dir and invokes gpte.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
        gcc python3-dev libffi-dev \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /work && chown 65534:65534 /work

RUN pip install --no-cache-dir 'gpt-engineer==0.3.1' \
 && apt-get purge -y gcc python3-dev libffi-dev \
 && apt-get autoremove -y

COPY runner.py /runner.py

USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python", "/runner.py"]
