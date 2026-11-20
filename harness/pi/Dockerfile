# pi CLI 镜像：构建一次，以只读方式挂载进每个 trial 容器。
# 镜像根目录等于 /usr/local 的内容（node、npm、pi），挂载点见 manifest.yaml。
# 版本由 scripts/build-harness.sh 从 manifest.yaml 传入。
FROM node:22-slim AS build

ARG PI_VERSION

RUN npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
  && pi --version

FROM scratch

ARG PI_VERSION
LABEL pi.version="${PI_VERSION}"

COPY --from=build /usr/local/ /
