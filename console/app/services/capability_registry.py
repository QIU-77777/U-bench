"""Capability registry: read harness definitions from the repo.

Everything the profile page shows comes from files users can edit:
configs/harnesses/*.yaml and harness/<name>/manifest.yaml.
This service only reads.
"""

from __future__ import annotations

import json

import yaml

from .. import config

_HARNESS_DIR = "configs/harnesses"
_MANIFEST_DIR = "harness"

_STANDARD_ENV = {
    "id": "standard",
    "name": "standard（任务自带环境）",
    "description": (
        "环境由任务自己的 environment/Dockerfile 定义，Harbor 构建并运行。"
        "编码与办公任务的工具链、数据、应用都放在任务镜像里，Agent 通过 shell 直接操作。"
    ),
}


def available_harnesses() -> list[str]:
    from . import profiles

    return profiles.available_harnesses()


def available_environments() -> list[str]:
    return ["standard"]


def harness_detail(harness_id: str) -> dict | None:
    """Aggregate a harness definition from its yaml, manifest and agent file."""
    path = config.REPO_ROOT / _HARNESS_DIR / f"{harness_id}.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None

    docs = data.get("param_docs") or {}
    params = [
        {"key": key, "value": value, "doc": str(docs.get(key) or "")}
        for key, value in (data.get("kwargs") or {}).items()
    ]
    detail = {
        "id": harness_id,
        "name": str(data.get("name") or harness_id),
        "protocol": str(data.get("protocol") or ""),
        "import_path": str(data.get("import_path") or ""),
        "image": _read_manifest(harness_id),
        "params": params,
        "agent": None,
        "notes": [],
    }
    if detail["agent"] is None:
        detail["notes"].append(
            "该 harness 的提示词与工具列表在镜像内的 CLI 中，仓库侧没有定义文件；"
            "改造需要修改镜像并重新构建。"
        )
    return detail


def environment_detail(env_id: str) -> dict | None:
    """Environment card. Only the standard environment exists for now; task
    environments are defined per task in their own Dockerfile."""
    if env_id == "standard":
        return {
            **_STANDARD_ENV,
            "tools": {"total": 0, "enabled": 0, "items": []},
            "data": {"entities": [], "seed_sha256": ""},
            "version": "",
        }
    return None


def _read_runtime_json(url: str) -> dict:
    """Best-effort read of a running service; the card stays usable without it."""
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_manifest(harness_id: str) -> dict:
    path = config.REPO_ROOT / _MANIFEST_DIR / harness_id / "manifest.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return {
        "repository": str(data.get("image_repository") or ""),
        "version": str(data.get("version") or ""),
        "mount_path": str(data.get("mount_path") or ""),
        "npm_package": str(data.get("npm_package") or ""),
    }



def _read_json(path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
