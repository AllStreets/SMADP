# Local-build adapter for open-interpreter. The upstream image at
# ghcr.io/openinterpreter/open-interpreter does not exist; this Dockerfile
# pip-installs from PyPI so SMADP has a buildable, sandbox-compatible image.
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

RUN pip install --no-cache-dir 'open-interpreter==0.4.3' \
 && apt-get purge -y gcc python3-dev libffi-dev \
 && apt-get autoremove -y

USER 65534:65534
WORKDIR /work
ENTRYPOINT ["interpreter"]
CMD ["--auto_run", "--no-tts", "--message", "hello"]
