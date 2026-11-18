# Harness image: pi CLI (glibc build), built once and mounted read-only
# into every trial container. Same layout contract as harness/pi: the image
# root is exactly the contents of /usr/local.
#
# Use this variant for Debian-based task images (wb-office tasks are
# python:3.12-slim); harness/pi (node:22-alpine, musl) stays the default for
# alpine-based task images. See harness/pi-debian/manifest.yaml.
FROM node:22-slim AS build

ARG PI_VERSION

RUN npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
  && pi --version

FROM scratch

ARG PI_VERSION
LABEL pi-debian.version="${PI_VERSION}"

COPY --from=build /usr/local/ /
