# Local-build adapter for crewai. The framework is python-only; we install
# from PyPI and ship a one-shot runner.py that constructs a single Agent +
# Task + Crew and prints the kickoff result.
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

RUN pip install --no-cache-dir 'crewai==1.14.6' \
 && apt-get purge -y gcc python3-dev libffi-dev \
 && apt-get autoremove -y

COPY runner.py /runner.py

USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python", "/runner.py"]
