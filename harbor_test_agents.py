"""挂载版 Harbor agent：CLI 来自预构建的 harness 镜像，不在每个 trial 里安装。

镜像按 ``harness/<name>/manifest.yaml`` 构建，由 agent 配置文件
（``configs/agents/*.yaml``）的 ``environment.mounts`` 以只读方式挂载到
``/opt/<name>``。每个类只替换 Harbor 原版 agent 的 ``install``，运行与轨迹
逻辑保持 Harbor 原版；``MountedOpenCode`` 另外把命令行换成 OpenCode v2 的写法
（全局参数放在 ``opencode run`` 之后，``--dangerously-skip-permissions``
改为 ``--auto``）。

Harbor agents whose CLI comes from a prebuilt harness image mounted read-only
at ``/opt/<name>`` instead of being installed per trial. Each class replaces
only ``install``; Harbor's own run and trajectory logic is untouched.
``MountedOpenCode`` also targets the OpenCode v2 command line.
"""

import shlex
from typing import override

from harbor.agents.installed.base import (
    NonZeroAgentExitCodeError,
    with_prompt_template,
)
from harbor.agents.installed.claude_code import ClaudeCode
from harbor.agents.installed.opencode import OpenCode
from harbor.agents.installed.pi import Pi
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


async def _require_cli(agent, environment: BaseEnvironment, binary: str) -> None:
    result = await agent.exec_as_agent(
        environment, command=f"command -v {binary} && {binary} --version"
    )
    if result.return_code != 0:
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        raise RuntimeError(
            f"{binary} CLI 不在容器内：检查 agent 配置的 environment.mounts 与 PATH。{output!r}"
        )


class MountedOpenCode(OpenCode):
    @override
    async def install(self, environment: BaseEnvironment) -> None:
        await _require_cli(self, environment, "opencode")

    @override
    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        self._instruction = instruction
        escaped_instruction = shlex.quote(instruction)

        if not self.model_name or "/" not in self.model_name:
            raise ValueError("Model name must be in the format provider/model_name")

        env = dict(self.model_connection.env)
        env["OPENCODE_FAKE_VCS"] = "git"
        env["XDG_DATA_HOME"] = (
            self.environment_logs_dir / "opencode" / "xdg-data"
        ).as_posix()
        env["XDG_STATE_HOME"] = (
            self.environment_logs_dir / "opencode" / "xdg-state"
        ).as_posix()

        skills_command = self._build_register_skills_command()
        if skills_command:
            await self.exec_as_agent(environment, command=skills_command, env=env)

        mcp_command = self._build_register_config_command()
        if mcp_command:
            await self.exec_as_agent(environment, command=mcp_command, env=env)

        cli_flags = self.build_cli_flags()
        cli_flags_arg = (cli_flags + " ") if cli_flags else ""
        resume_flag = "--continue " if self._resume else ""

        await self.exec_as_agent(
            environment,
            command=(
                f"opencode run --model={self.model_name} --format=json "
                f"{resume_flag}{cli_flags_arg}--thinking --auto "
                f"-- {escaped_instruction} "
                f"2>&1 </dev/null | stdbuf -oL tee "
                f"{shlex.quote((self.environment_logs_dir / self._OUTPUT_FILENAME).as_posix())}"
            ),
            env=env,
        )

        if messages := self._error_messages():
            raise NonZeroAgentExitCodeError(
                "OpenCode emitted error event(s): " + "; ".join(messages[:3])
            )


class MountedPi(Pi):
    @override
    async def install(self, environment: BaseEnvironment) -> None:
        await _require_cli(self, environment, "pi")


class MountedClaudeCode(ClaudeCode):
    @override
    async def install(self, environment: BaseEnvironment) -> None:
        # 作业快照保留 provider/model-id；Claude Code 只接收模型 ID。
        if self.model_name and "/" in self.model_name:
            self.model_name = self.model_name.split("/", 1)[1]
            self._init_model_info()
        await _require_cli(self, environment, "claude")
