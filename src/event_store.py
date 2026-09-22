"""只追加事件存储。

平台回执与批量导入可能重复或乱序，因此存储层保证：
- 幂等：同一 event_id 重复写入且内容一致 → 视为重复投递，忽略；
  内容不一致 → ConflictError（数据冲突，必须人工处理，不能静默覆盖）；
- 乱序：事件按 (occurred_at, event_id) 排序回放，与写入先后无关；
- 只追加：不提供更新与删除，历史事件不可改写。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.contract import validate_event
from src.domain import ConflictError, DomainError, parse_ts


def _canonical(record: dict) -> str:
    """规范化序列化，用于重复事件的内容一致性比较。"""
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class ImportReport:
    """批量导入回执：总数、新增、重复（幂等忽略）、拒绝（校验失败）。"""

    total: int
    added: int
    duplicates: int
    rejected: int


class EventStore:
    def __init__(self) -> None:
        self._events: dict[str, dict] = {}
        self._canonical: dict[str, str] = {}

    def append(self, record: dict) -> bool:
        """写入一条事件。返回 True 表示新增，False 表示重复投递被忽略。"""
        errors = validate_event(record)
        if errors:
            raise DomainError(f"事件校验失败 {record.get('event_id')!r}: {'; '.join(errors)}")
        event_id = record["event_id"]
        canonical = _canonical(record)
        if event_id in self._events:
            if self._canonical[event_id] != canonical:
                raise ConflictError(f"event_id {event_id!r} 已存在且内容不一致，拒绝覆盖")
            return False
        self._events[event_id] = record
        self._canonical[event_id] = canonical
        return True

    def import_batch(self, records: list[dict]) -> ImportReport:
        """批量导入：逐条 append，校验失败与冲突计入 rejected，不中断整批。"""
        added = duplicates = rejected = 0
        for record in records:
            try:
                if self.append(record):
                    added += 1
                else:
                    duplicates += 1
            except DomainError:
                rejected += 1
        return ImportReport(total=len(records), added=added, duplicates=duplicates, rejected=rejected)

    def replay(self, subject_id: str | None = None) -> list[dict]:
        """按 (occurred_at, event_id) 排序回放；可选按主体过滤。"""
        events = [e for e in self._events.values() if subject_id is None or e["subject_id"] == subject_id]
        return sorted(events, key=lambda e: (parse_ts(e["occurred_at"]), e["event_id"]))

    def subjects(self, kind: str | None = None) -> list[str]:
        """列出出现过事件的主体标识，可按事件类型过滤。"""
        seen = {e["subject_id"] for e in self._events.values() if kind is None or e["kind"] == kind}
        return sorted(seen)

    def __len__(self) -> int:
        return len(self._events)
