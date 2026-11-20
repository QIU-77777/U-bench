# code-basic-v1

三个难度递增的 Python 代码任务，均为 Harbor 原生布局（`instruction.md`、`task.toml`、`environment/`、`solution/solve.sh`、`tests/test.sh`）。

| 任务 | 内容 |
|---|---|
| `fix-failing-tests` | 修复 `cart` 包中的 3 处 bug，使单元测试通过；隐藏测试多出边界用例 |
| `implement-cli-tool` | 实现 CSV 分组聚合命令行工具 `csvagg.py`，含参数校验与退出码 |
| `refactor-keep-behavior` | 重构重复的报表模块，输出保持不变，并满足指定的函数与类结构 |

## 评分

`tests/test.sh` 在 `/workspace` 运行隐藏的 `tests/test_hidden.py`，reward 为通过的用例数除以总用例数（0 到 1），写入 `/logs/verifier/reward.json`。没有收集到任何用例时，verifier 不写 reward 并以非零码退出。

## 验收

```bash
export PATH=$PATH:/Applications/Docker.app/Contents/Resources/bin
scripts/run.sh --oracle code-basic -q
.venv/bin/harbor run -c configs/benches/code-basic.yaml -a nop --env-file .env -y -q --job-name code-basic-nop-check
```

参考解运行后三个任务的 reward 均为 1.0；空操作 agent 的 reward 均小于 1.0。
