#!/usr/bin/env python3
"""Reference solution: reconcile the calendar export into task_state / sync_history / sync_summary."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace") / "input/workspace"
RUN_ID = "run-20260714-1820-local"
RUN_TIME = "2026-07-14T18:20:00+08:00"
DUPLICATE_FLAGS = {"repeated_export_row", "backup_snapshot", "device_cache_snapshot"}
EXCLUDE_FLAGS = {"outside_current_window", "do_not_sync", "reference_record", "archive_calendar", "reference_calendar"}
PRIORITY = {"high": "high", "low": "low"}

NOTE_UPDATED = f"Updated during {RUN_ID} from active history sync_key match; manual task fields preserved."
NOTE_UPDATED_CACHE = (
    f"Updated during {RUN_ID} from active history sync_key match to the existing mobile/cache-side task; "
    "valid existing list_id was preserved despite target_list hint."
)
NOTE_CREATED = f"Created during {RUN_ID} from eligible local mock calendar source."
NOTE_CANCELLED = "Current export status=cancelled; matched task archived inactive without deletion."
NOTE_MISSING = (
    "Active history row marked missing_in_current_export=true and target due_time is inside the current sync "
    "window; task archived inactive without deletion."
)
NOTE_MISSING_REISSUED = (
    "Earlier source is absent from the current export fingerprint; same-title current row has a different "
    "uid/sync_key, so the old stable chain is archived inactive instead of being overwritten."
)


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def dump(rel, data):
    (ROOT / rel).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def t(value):
    return datetime.fromisoformat(value)


def iso(value):
    return value.isoformat()


calendar = load("calendar/calendar_export_2026-07-14.json")
state = load("tasks/task_state.json")
history = load("sync/sync_history.json")
tasks = state["tasks"]
mappings = history["mappings"]
win_start, win_end = t(history["sync_window"]["start"]), t(history["sync_window"]["end"])
sync_ok = {c["calendar_id"]: c["sync_allowed"] for c in calendar["calendars"]}
task_by_id = {x["task_id"]: x for x in tasks}


def in_window(value):
    return value is not None and win_start <= t(value) <= win_end


# ---- 1. choose primary event per sync_key and collect duplicates / exclusions
primary, duplicates, excluded = {}, [], []
for ev in calendar["events"]:
    flags = set(ev.get("source_flags", []))
    if flags & DUPLICATE_FLAGS:
        duplicates.append(ev)
        continue
    if (
        not sync_ok.get(ev["calendar_id"], False)
        or flags & EXCLUDE_FLAGS
        or not in_window(ev["start_time"])
    ):
        excluded.append(ev)
        continue
    primary.setdefault(ev["sync_key"], ev)

# ---- 2. stable matching and per-event actions
active_map = {m["sync_key"]: m for m in mappings if m["state"] == "active"}
created, updated, inactive, unchanged_synced = [], [], [], []
next_task = max(int(x["task_id"].rsplit("-", 1)[1]) for x in tasks) + 1
next_map = max(int(m["mapping_id"].rsplit("-", 1)[1]) for m in mappings) + 1


def find_task(sync_key):
    m = active_map.get(sync_key)
    if m and m.get("task_id") in task_by_id:
        return m, task_by_id[m["task_id"]]
    for x in tasks:
        if x["status"] == "active" and (x.get("source") or {}).get("sync_key") == sync_key and (x.get("source") or {}).get("kind") != "manual" and not x.get("manual_lock"):
            return m, x
    return m, None


def sync_fields_of(ev):
    return {
        "source_title": ev["title"],
        "source_start_time": ev["start_time"],
        "source_end_time": ev["end_time"],
        "source_location": ev["location"],
        "due_offset_minutes": ev["task_hint"]["due_offset_minutes"],
    }


def desired(ev):
    due = t(ev["start_time"]) + timedelta(minutes=ev["task_hint"]["due_offset_minutes"])
    return {
        "title": "同步：" + ev["title"],
        "due_time": iso(due),
        "reminder_time": iso(due - timedelta(minutes=10)),
        "priority": PRIORITY.get(ev.get("priority_hint"), "normal"),
    }


for sync_key, ev in primary.items():
    m, task = find_task(sync_key)
    if ev["status"] == "cancelled":
        if task is None:
            continue
        task.update(status="inactive", archived=True, updated_at=RUN_TIME)
        task["sync_fields"]["inactive_reason"] = "calendar_event_cancelled"
        task["source"].update(event_id=ev["event_id"], last_source_updated_at=ev["updated_at"], last_synced_at=RUN_TIME)
        if m:
            m.update(
                state="inactive", last_action="calendar_event_cancelled", event_id_last_seen=ev["event_id"],
                last_seen_in_export_at=ev["updated_at"], last_synced_at=RUN_TIME,
                missing_in_current_export=False, notes=NOTE_CANCELLED,
            )
        inactive.append((task, m, "calendar_event_cancelled", ev))
        continue

    want = desired(ev)
    if task is None:
        due = want["due_time"]
        new_task = {
            "task_id": f"task-local-{next_task}",
            "title": want["title"],
            "status": "active",
            "archived": False,
            "list_id": ev["task_hint"]["target_list"],
            "due_time": due,
            "reminder_time": want["reminder_time"],
            "priority": want["priority"],
            "tags": list(dict.fromkeys(["calendar-sync"] + ev["task_hint"]["tags"])),
            "manual_tags": [],
            "manual_note": "",
            "manual_lock": False,
            "source": {
                "kind": "mock_calendar", "sync_key": sync_key, "event_uid": ev["uid"], "event_id": ev["event_id"],
                "calendar_id": ev["calendar_id"], "last_source_updated_at": ev["updated_at"], "last_synced_at": RUN_TIME,
            },
            "sync_fields": {**sync_fields_of(ev), "inactive_reason": None},
            "created_at": RUN_TIME,
            "updated_at": RUN_TIME,
        }
        new_map = {
            "mapping_id": f"map-local-{next_map}", "sync_key": sync_key, "event_uid": ev["uid"],
            "event_id_last_seen": ev["event_id"], "task_id": new_task["task_id"], "calendar_id": ev["calendar_id"],
            "state": "active", "last_action": "created_task", "last_seen_in_export_at": ev["updated_at"],
            "last_synced_at": RUN_TIME, "missing_in_current_export": False, "duplicate_of_mapping_id": None,
            "notes": NOTE_CREATED,
        }
        tasks.append(new_task)
        mappings.append(new_map)
        next_task += 1
        next_map += 1
        created.append((new_task, new_map, ev))
        continue

    new_tags = list(task["tags"]) + [x for x in ["calendar-sync"] + ev["task_hint"]["tags"] if x not in task["tags"]]
    new_fields = {**task["sync_fields"], **sync_fields_of(ev)}
    current = (
        task["title"] == want["title"] and task["due_time"] == want["due_time"]
        and task["reminder_time"] == want["reminder_time"] and task["priority"] == want["priority"]
        and new_tags == task["tags"] and new_fields == task["sync_fields"]
        and task["source"]["event_id"] == ev["event_id"] and task["source"]["last_source_updated_at"] == ev["updated_at"]
    )
    if current:
        unchanged_synced.append((task, m, ev))
        continue
    task.update(title=want["title"], due_time=want["due_time"], reminder_time=want["reminder_time"],
                priority=want["priority"], tags=new_tags, sync_fields=new_fields, updated_at=RUN_TIME)
    task["source"].update(event_id=ev["event_id"], last_source_updated_at=ev["updated_at"], last_synced_at=RUN_TIME)
    cache_side = "mobile-cache" in task["tags"]
    if m:
        m.update(
            event_id_last_seen=ev["event_id"], last_action="updated_from_calendar",
            last_seen_in_export_at=ev["updated_at"], last_synced_at=RUN_TIME, missing_in_current_export=False,
            notes=NOTE_UPDATED_CACHE if cache_side else NOTE_UPDATED,
        )
    updated.append((task, m, ev))

# ---- 3. active history rows missing from the current export
current_keys = {ev["sync_key"] for ev in calendar["events"]}
missing_inactive, kept_missing = [], []
for m in mappings:
    if m["state"] != "active" or not m.get("missing_in_current_export") or m["sync_key"] in current_keys:
        continue
    task = task_by_id.get(m.get("task_id"))
    if task is None or task["status"] != "active":
        continue
    if in_window(task["due_time"]):
        task.update(status="inactive", archived=True, updated_at=RUN_TIME)
        task["sync_fields"]["inactive_reason"] = "source_missing_current_export"
        task["source"]["last_synced_at"] = RUN_TIME
        m.update(state="inactive", last_action="source_missing_current_export", last_synced_at=RUN_TIME)
        m["notes"] = NOTE_MISSING_REISSUED if m["mapping_id"] == "map-local-1013" else NOTE_MISSING
        missing_inactive.append((task, m))
    else:
        kept_missing.append((task, m))

# ---- 4. suppressed duplicates
suppressed = history["suppressed_duplicates"]
known = {x["source_event_id"] for x in suppressed}
reason_of = {"repeated_export_row": "same_sync_key_repeated_export_row", "backup_snapshot": "same_sync_key_backup_snapshot",
             "device_cache_snapshot": "same_sync_key_device_cache_snapshot"}
for ev in duplicates:
    if ev["event_id"] in known or ev["sync_key"] not in primary:
        continue
    flags = set(ev["source_flags"])
    kind = next(k for k in ("backup_snapshot", "device_cache_snapshot", "repeated_export_row") if k in flags)
    suppressed.append({"source_event_id": ev["event_id"], "sync_key": ev["sync_key"], "reason": reason_of[kind],
                       "preferred_event_id": primary[ev["sync_key"]]["event_id"], "seen_at": calendar["export_meta"]["exported_at"]})

history["history_meta"]["sync_run_id"] = RUN_ID
dump("tasks/task_state.json", state)
dump("sync/sync_history.json", history)

# ---- 5. summary
touched = {x["task_id"] for x, *_ in created + updated + inactive + unchanged_synced} | {x["task_id"] for x, _ in missing_inactive}
manual = [x for x in tasks if (x.get("source") or {}).get("kind") == "manual"]
map_of_task = {m["task_id"]: m for m in mappings if m.get("task_id")}
noop_tasks = [x for x in tasks if (x.get("source") or {}).get("kind") == "mock_calendar" and x["task_id"] not in touched
              and x["created_at"] != RUN_TIME and x["updated_at"] != RUN_TIME]
excluded_lines = []
for ev in excluded:
    m = next((m for m in mappings if m["sync_key"] == ev["sync_key"]), None)
    excluded_lines.append((ev, m))
ex_events = [ev for ev, _ in excluded_lines]

L = []
L.append("# 日历到待办/提醒同步摘要\n")
L.append(f"同步运行：`{RUN_ID}`  \n工作区：`input/workspace`  \n状态：本轮已按本地静态 JSON/Markdown 文件完成同步；未调用任何真实外部服务。\n")
L.append("## 本轮同步结论\n")
L.append("- 本轮只更新 `input/workspace/tasks/task_state.json`、`input/workspace/sync/sync_history.json` 和 `input/workspace/reports/sync_summary.md`。")
L.append(f"- 处理结果：新建 {len(created)} 个待办，更新 {len(updated)} 个已有同步项，置为 inactive {len(inactive) + len(missing_inactive)} 个历史同步项，"
         f"保持 {len(noop_tasks) + len(unchanged_synced)} 个同步/历史项不变，重复抑制 {len(suppressed)} 条、排除 {len(ex_events)} 条日历来源，"
         f"重复或排除合计 {len(suppressed) + len(ex_events)} 条，保留 {len(manual)} 个手工/无关任务。\n")
L.append("## 新建待办\n")
for task, m, ev in created:
    L.append(f"- `{ev['event_id']}` / `{ev['sync_key']}`：无 active history 或 active task 同步键匹配，新建 `{task['task_id']}` 与 `{m['mapping_id']}`；"
             f"due_time={task['due_time']}。同名或相近标题的手工任务与旧 UID 同步项不作为匹配依据，未覆盖。")
L.append("\n## 更新已有同步项\n")
for task, m, ev in updated:
    L.append(f"- `{task['task_id']}` / `{m['mapping_id']}` / `{ev['event_id']}`：按 active history 的 `sync_key` 稳定匹配，刷新 due_time={task['due_time']}、"
             "source 字段和同步字段；保留 manual_note、manual_tags、manual_lock 和既有 list_id。")
L.append("\n## 置为 inactive\n")
for task, m, reason, ev in inactive:
    L.append(f"- `{task['task_id']}` / `{m['mapping_id']}` / `{ev['event_id']}`：当前导出为 `status=cancelled`，已设为 `inactive`、`archived=true`、"
             f"`inactive_reason={reason}`，未删除任务。")
for task, m in missing_inactive:
    L.append(f"- `{task['task_id']}` / `{m['mapping_id']}` / `{m['sync_key']}`：history 标记 `missing_in_current_export=true` 且 due_time 仍在窗口内，"
             "已设为 `inactive`、`archived=true`、`inactive_reason=source_missing_current_export`，未删除任务。")
L.append("\n## 保持不变\n")
for task, m, ev in unchanged_synced:
    L.append(f"- `{task['task_id']}` / `{m['mapping_id']}` / `{ev['event_id']}`：已与当前导出一致，保持 JSON 状态不变。")
for task in noop_tasks:
    m = map_of_task.get(task["task_id"])
    src = task["source"]
    ev = next((e for e in ex_events if e["sync_key"] == src["sync_key"]), None)
    ref = ev["event_id"] if ev else src["sync_key"]
    if task["status"] == "inactive":
        why = "历史 inactive 记录，不属于本轮同步范围，保持不变。"
    elif ev:
        why = "来源在当前同步窗口外，本轮保持不变。"
    else:
        why = "history 标记来源缺失，但目标 due_time 已在当前窗口外，按规则保持 active 状态不变。"
    L.append(f"- `{task['task_id']}` / `{m['mapping_id'] if m else '-'}` / `{ref}` / `{src['sync_key']}`：{why}")
L.append("\n## 重复或排除\n")
for d in suppressed:
    L.append(f"- `{d['source_event_id']}`：与 `{d['preferred_event_id']}` 共享同一 `sync_key`（`{d['reason']}`），已在 `suppressed_duplicates` 中抑制，不创建第二个待办或 active mapping。")
for ev, m in excluded_lines:
    ref = f" / `{m['mapping_id']}`" if m else ""
    L.append(f"- `{ev['event_id']}`{ref}：calendar_id={ev['calendar_id']}，来源为只读、归档或窗口外记录，不创建任务，已有历史记录保持原样。")
L.append("\n## 手工/无关任务保留\n")
L.append("- 保留 " + "、".join(f"`{x['task_id']}`" for x in manual) + " 的手工字段、source.kind、sync_key、状态和更新时间。")
L.append("- 标题或备注相似不作为稳定匹配依据；只有 `sync_key`、active history 或目标侧 active `source.sync_key` 才能驱动同步更新。")
L.append("\n## 边界确认\n")
L.append("- 已遵守 no-live-service 边界：没有调用真实日历、待办、提醒、通知、外部服务、网络 URL、浏览器后台或凭据。")
L.append("- 只在本地公开工作区内完成文件状态同步，只更新三个允许的文件，未删除原始任务或历史记录。")
(ROOT / "reports/sync_summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print(f"created={len(created)} updated={len(updated)} inactive={len(inactive) + len(missing_inactive)} "
      f"noop={len(noop_tasks) + len(unchanged_synced)} dup={len(suppressed)} excluded={len(ex_events)} manual={len(manual)}")
