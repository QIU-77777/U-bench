#!/bin/bash
# Ensure the public base images used by wb-office task Dockerfiles exist in
# the local Docker image store.
#
# The task images are FROM python:3.12-slim, but Docker Hub is unreachable
# from this machine. When a compatible image is already cached under a
# mirror name, retag it; otherwise try a normal pull.
#
# Usage: scripts/ensure-base-images.sh
set -euo pipefail

need_tag() {
    local tag="$1"
    if docker image inspect "$tag" >/dev/null 2>&1; then
        echo "OK $tag (present)"
        return 0
    fi
    echo "MISSING $tag"
    return 1
}

retag_from_cache() {
    local tag="$1"; shift
    local candidate
    for candidate in "$@"; do
        if docker image inspect "$candidate" >/dev/null 2>&1; then
            docker tag "$candidate" "$tag"
            echo "RETAGGED $tag <- $candidate (mirror cache)"
            return 0
        fi
    done
    return 1
}

if ! need_tag python:3.12-slim; then
    if ! retag_from_cache python:3.12-slim \
        docker.m.daocloud.io/library/python:3.12-slim \
        docker.m.daocloud.io/library/python:3.12.9-slim; then
        echo "pulling python:3.12-slim (needs Docker Hub or a configured mirror)"
        docker pull python:3.12-slim
    fi
fi

# node:22-slim backs the pi-debian harness image (glibc build for
# Debian-based task images). Docker Hub is unreachable here; the daocloud
# mirror is the fallback.
if ! need_tag node:22-slim; then
    if ! retag_from_cache node:22-slim \
        docker.m.daocloud.io/library/node:22-slim; then
        echo "pulling node:22-slim (needs Docker Hub or a configured mirror)"
        if ! docker pull node:22-slim; then
            echo "plain pull failed; trying daocloud mirror"
            docker pull docker.m.daocloud.io/library/node:22-slim
            docker tag docker.m.daocloud.io/library/node:22-slim node:22-slim
        fi
    fi
fi

docker image inspect python:3.12-slim >/dev/null 2>&1 \
    || { echo "ERROR: python:3.12-slim still unavailable" >&2; exit 1; }
echo "base images ready"
