"""只追加事件存储。

- 事件一旦追加不可修改、不可删除（监管留置要求亦建立在此之上）。
- event_id 全局幂等：重复登记同一 event_id 返回既有事件；同号不同内容视为冲突。
- version 为同一 subject_id 内的追加序号（1 起），与业务时间 occurred_at 解耦：
  乱序到达合法，投影一律按 occurred_at 重排事实。
"""
from datetime import datetime

from .contract import require_valid
from .errors import ConflictError
from . import catalog


class EventStore:
    def __init__(self):
        self._events: dict[str, list[dict]] = {}
        self._by_id: dict[str, dict] = {}

    # ---- 写入 ----
    def append(self, event: dict) -> dict:
        require_valid(event)
        eid = event["event_id"]
        existing = self._by_id.get(eid)
        if existing is not None:
            if existing == event:
                return existing  # 幂等：完全相同的重复投递
            raise ConflictError(f"event_id {eid} 已存在且内容不同，事件不可改写")

        subject = event["subject_id"]
        stream = self._events.setdefault(subject, [])
        expected_version = len(stream) + 1
        if event["version"] != expected_version:
            raise ConflictError(
                f"{subject}: version 应为 {expected_version}，收到 {event['version']}；"
                "事件只能顺序追加（业务时间乱序请使用 occurred_at 表达）"
            )
        stored = dict(event)
        stream.append(stored)
        self._by_id[eid] = stored
        return stored

    # ---- 读取 ----
    def stream(self, subject_id: str) -> list[dict]:
        """返回按业务时间 (occurred_at, version) 重排的不可变副本列表。"""
        events = [dict(e) for e in self._events.get(subject_id, [])]
        events.sort(key=lambda e: (datetime.fromisoformat(e["occurred_at"]), e["version"]))
        return events

    def get(self, event_id: str) -> dict | None:
        event = self._by_id.get(event_id)
        return dict(event) if event else None

    def subjects(self) -> list[str]:
        return sorted(self._events)

    def next_version(self, subject_id: str) -> int:
        return len(self._events.get(subject_id, [])) + 1

    def all_events(self) -> list[dict]:
        return [dict(e) for s in self.subjects() for e in self._events[s]]


def is_receipt(event: dict) -> bool:
    return (
        event.get("kind") == catalog.KIND_EVIDENCE_UPLOADED
        and event.get("payload", {}).get("evidence_type") == catalog.EV_RECEIPT
    )


def receipt_fingerprint(event: dict) -> tuple:
    """平台回执去重指纹：同一主体 + 来源 + 内容哈希即视为同一回执。"""
    p = event["payload"]
    return (event["subject_id"], p.get("source"), p.get("raw_hash"))
