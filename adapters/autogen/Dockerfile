# Local-build adapter for autogen. The published ghcr.io/microsoft/autogen
# image is unavailable, so we pip-install autogen-agentchat directly and ship
# a thin one-shot CLI wrapper (runner.py) since autogen has no native CLI.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /work && chown 65534:65534 /work

# autogen-agentchat ships only wheels (no native build deps required on arm64).
RUN pip install --no-cache-dir 'autogen-agentchat==0.7.5' 'autogen-ext[openai]==0.7.5'

COPY runner.py /runner.py

USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python", "/runner.py"]
