# 本地 mock 日历同步摘要

同步运行：`run-20260714-1820-local`  
工作区：`input/workspace`  
状态：本轮已按本地静态 JSON/Markdown 文件完成同步；未调用任何真实外部服务。

## 本轮同步结论

- 本轮只更新 `input/workspace/tasks/task_state.json`、`input/workspace/sync/sync_history.json` 和 `input/workspace/reports/sync_summary.md`。
- 处理结果：新建 4 个待办，更新 3 个已有同步项，置为 inactive 4 个历史同步项，保持 5 个同步/历史项不变，重复抑制 4 条、排除 4 条日历来源，重复或排除合计 8 条，保留 7 个手工/无关任务。

## 新建待办

- `evt-20260715-briefing-A` / `cal::uid-local-briefing-20260715::2026-07-15`：无 active history 或 active task 同步键，完成本地 mock task 追加。
- `evt-20260715-vendor-review-A` / `cal::uid-local-vendor-review-20260715::2026-07-15`：无稳定匹配；标题相似的 `task-local-2007` 是 manual_lock 手工任务，未覆盖，完成本地 mock task 追加。
- `evt-20260717-onsite-A` / `cal::uid-local-onsite-20260717::2026-07-17`：无稳定匹配；`task-local-2012` 为手工门禁事项，未覆盖，完成本地 mock task 追加。
- `evt-20260717-contract-new-A` / `cal::uid-local-contract-renewal-20260717-v2::2026-07-17`：同名旧同步项 `task-local-2019` 使用不同 `sync_key` 且来源缺失，不能被覆盖；新 UID/source instance 完成本地 mock task 追加。

## 更新已有同步项

- `task-local-2001` / `map-local-1001` / `evt-20260716-budget-A`：按 active history 的 `sync_key` 更新预算会议的 due_time、source 字段和同步字段；保留 manual_note 与 manual_tags。
- `task-local-2002` / `map-local-1002` / `evt-20260719-review-moved-A`：按 active history 的 `sync_key` 更新周报复核的新时间、地点、source 字段和同步字段；保留 manual_note。
- `task-local-2017` / `map-local-1011` / `evt-20260718-training-A`：按已有手机端/缓存侧 active `sync_key` 稳定匹配，刷新周末演练提醒的 due_time、event_id 和同步字段；保留 manual_note、manual_tags、既有本地标签和有效既有 list_id，不按 `target_list=list_personal_buffer` 迁移列表。

## 置为 inactive

- `task-local-2003` / `map-local-1003` / `evt-20260720-demo-cancelled-A`：当前导出为 `status=cancelled`，已设为 `inactive`、`archived=true`、`inactive_reason=calendar_event_cancelled`，未删除任务。
- `task-local-2004` / `map-local-1004` / `evt-20260721-checkout-cancelled-A`：当前导出为 `status=cancelled`，已设为 `inactive`、`archived=true`、`inactive_reason=calendar_event_cancelled`，未删除任务。
- `task-local-2005` / `map-local-1005` / `cal::uid-local-doc-freeze-20260718::2026-07-18`：history 标记 `missing_in_current_export=true` 且 due_time 仍在窗口内，已设为 `inactive`、`archived=true`、`inactive_reason=source_missing_current_export`，未删除任务。
- `task-local-2019` / `map-local-1013` / `cal::uid-local-contract-renewal-20260717-v1::2026-07-17`：同名当前来源 `evt-20260717-contract-new-A` 使用不同 UID/`sync_key`，旧 stable chain 来源缺失且 due_time 在窗口内，已设为 `inactive`、`archived=true`、`inactive_reason=source_missing_current_export`，未删除或覆盖旧任务。

## 保持不变

- `task-local-2006` / `map-local-1006` / `evt-20260716-briefing-shift-A`：已与当前导出一致，保持 JSON 状态不变。
- `task-local-2009` / `map-local-1007` / `evt-20260724-after-window-A`：来源在当前同步窗口外，本轮保持不变。
- `task-local-2014` / `map-local-1008` / `evt-archive-20260630-A`：历史归档 inactive 记录，不属于本轮同步范围，保持不变。
- `task-local-2015` / `map-local-1009` / `cal::uid-local-briefing-old-20260715::2026-07-15`：旧实例已 inactive，不作为本轮 active 匹配目标，保持不变。
- `task-local-2018` / `map-local-1012` / `cal::uid-local-after-window-missing-20260722::2026-07-22`：history 标记来源缺失，但目标 due_time 已在当前窗口外，按规则保持 active 状态不变。

## 重复或排除

- `evt-20260715-briefing-duplicate-B`：与 `evt-20260715-briefing-A` 共享同一 `sync_key`，保留在 `suppressed_duplicates`，不创建第二个待办。
- `evt-20260716-budget-shadow-B`：与 `evt-20260716-budget-A` 共享同一 `sync_key`，保留在 `suppressed_duplicates`，不创建第二个待办或 active mapping。
- `evt-20260719-review-duplicate-B`：与 `evt-20260719-review-moved-A` 共享同一 `sync_key`，保留在 `suppressed_duplicates`，不创建第二个待办。
- `evt-20260719-review-near-window-shadow-C`：与 `evt-20260719-review-moved-A` 共享同一 `sync_key`，保留在 `suppressed_duplicates`，不按缓存行时间另建待办。
- `evt-20260716-readonly-lunch-A` / `map-local-1010`：只读日历 excluded，未创建任务，未修改手工午间任务。
- `evt-20260724-after-window-A`：窗口外来源，不创建新任务；既有 `task-local-2009` 保持。
- `evt-20260714-before-window-A`：窗口前来源，不创建任务或 mapping。
- `evt-archive-20260630-A` / `map-local-1008`：归档日历/历史 inactive 记录，保持排除和历史状态。

## 手工/无关任务保留

- 保留 `task-local-2007`、`task-local-2008`、`task-local-2010`、`task-local-2011`、`task-local-2012`、`task-local-2013`、`task-local-2016` 的手工字段、source.kind、sync_key、状态和更新时间。
- 标题或备注相似不作为稳定匹配依据；只有 `sync_key`、active history 或目标侧 active `source.sync_key` 才能驱动同步更新。

## 边界确认

- 已遵守 no-live-service 边界：没有调用真实日历、待办、提醒、通知、外部服务、网络 URL、浏览器后台、API、MCP、Skill 或凭据。
- 只在本地公开工作区内完成文件状态同步，未删除原始任务或历史记录，未修改只读日历导出、规则、notes、README 或 environment 文件。
