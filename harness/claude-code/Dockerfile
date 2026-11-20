# Claude Code CLI 镜像：构建一次，以只读方式挂载进每个 trial 容器。
# 镜像根目录等于 /usr/local 的内容（node、npm、claude），挂载点见 manifest.yaml。
# 版本由 scripts/build-harness.sh 从 manifest.yaml 传入。
FROM node:22-slim AS build

ARG CLAUDE_CODE_VERSION

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && claude --version

FROM scratch

ARG CLAUDE_CODE_VERSION
LABEL claude-code.version="${CLAUDE_CODE_VERSION}"

COPY --from=build /usr/local/ /
