将专用同步工作区里的日历导出同步到工作区待办/提醒，并按规则把已取消或本轮来源缺失的同步项标记为 inactive。请实际更新状态文件，不要只做分析。

本轮同步时间：`2026-07-14T18:20:00+08:00` / `2026-07-14T10:20:00Z`。

## 工具和材料

全部材料都在本任务目录内。先阅读：

- `input/workspace/README_先读我.md`
- `input/workspace/rules/sync_policy.md`
- `input/workspace/calendar/calendar_export_2026-07-14.json`
- `input/workspace/tasks/task_state.json`
- `input/workspace/sync/sync_history.json`
- `input/workspace/notes/operator_notes.txt`
- `environment/local_mock_sync/README.md`

## 只允许写入

只更新这三个文件：

- `input/workspace/tasks/task_state.json`
- `input/workspace/sync/sync_history.json`
- `input/workspace/reports/sync_summary.md`

不要修改日历导出、规则文件、notes、README、环境说明或任何未列入上方清单的文件。

## 流程

### Step 1：读取同步记录和待办状态

读取 `sync_history.json` 与 `task_state.json`，确认已有 active mapping、目标侧 `sync_key`、手工任务、`manual_note`、`manual_lock`、手工标签和 inactive/archived 状态。

### Step 2：读取本轮日历导出

读取 `calendar_export_2026-07-14.json`，只处理公开同步窗口内、本轮应同步的日历记录。只读日历、窗口外记录、缓存/备份重复导出行和不应进入同步范围的记录只作为排除依据。

### Step 3：同步新日程

对本轮应同步、且没有 active history 或目标侧稳定匹配的日历记录，新建工作区待办/提醒。同一个 `sync_key` 只能对应一个 active 待办；不要用标题相似或时间近似去改手工任务。

### Step 4：更新已有同步项

对已有稳定匹配项，只更新日历同步相关字段和同步历史；不要覆盖 `manual_note`、`manual_lock`、手工标签或无关手工任务。已与日历源一致的同步项保持不变。

### Step 5：处理取消和来源缺失

- 已匹配但日历记录 `status=cancelled`：把目标任务置为 `inactive`、`archived=true`，并写明 `inactive_reason=calendar_event_cancelled`；不要删除任务。
- 历史记录标记为本轮来源缺失、且目标 `due_time` 仍在当前同步窗口内的 active 项：置为 `inactive`、`archived=true`，并写明 `inactive_reason=source_missing_current_export`；不要删除任务。
- 来源缺失但目标 `due_time` 已在当前窗口外的记录，本轮保持 active 状态不变。

### Step 6：去重和保留

重复导出、同 `sync_key` 的缓存/备份行、同名但不同 `sync_key` 的来源实例、标题相似但没有同步键的手工任务，都不能制造重复待办或错误更新。`sync_history.json` 中新增或更新的 mapping 要与任务状态里的 `sync_key`、`task_id`、event uid、last_action 和时间戳一致。

### Step 7：写同步摘要

按 `sync_summary.md` 的原有稳定标题填写本次同步结果。新建、更新、inactive、无变化、重复/排除、手工保留等 item references、原因和分类必须与两个 JSON 文件的实际更新一致。

## 注意事项

- 所有改动都只能体现在上述 JSON / Markdown 文件中。
- 不要调用真实日历、待办、提醒、通知、外部服务、网络 URL、浏览器后台或任何 live service。
- 不要引用私有来源细节、真实账号、认证材料、真实个人/客户/组织数据或本工作区之外的事实。
- 如果某条记录无法按稳定键匹配，就按规则保留或排除，不要用标题猜测。

最后请用简短中文回复：更新了哪些文件、新增/更新/置 inactive 的概况、哪些项目被重复抑制或手工保留，以及是否没有访问真实外部服务。
