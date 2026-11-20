FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends git bash ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "pytest==8.3.4"

WORKDIR /workspace

COPY workspace/ /workspace/

RUN git config --global user.email "dev@project" && \
    git config --global user.name "Developer" && \
    git init -q -b main && git add -A && git commit -q -m "initial setup"
