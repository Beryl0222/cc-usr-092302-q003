"""批量导入：容忍重复与乱序。

- 乱序：批量内先按 occurred_at 稳定排序，再逐主题分配 version 追加。
- 重复：event_id 完全相同的重复事件跳过（幂等）；
  平台回执另按 (subject, source, raw_hash) 指纹去重。
- 批次中任何单条非法不影响其余条目，问题条目收集在 IngestReport.rejected。
"""
from dataclasses import dataclass, field
from datetime import datetime

from .contract import validate_event
from .errors import ConflictError, DomainError
from .store import EventStore, is_receipt, receipt_fingerprint


@dataclass
class IngestReport:
    accepted: list[str] = field(default_factory=list)    # event_id
    duplicates: list[str] = field(default_factory=list)  # event_id（含回执指纹重复）
    rejected: list[dict] = field(default_factory=list)   # {"event_id", "errors"}

    @property
    def ok(self) -> bool:
        return not self.rejected


def _assign_versions(batch: list[dict], store: EventStore) -> list[dict]:
    """按主题重排并补齐 version；调用者保证 event_id 唯一且信封合法。"""
    pending: dict[str, list[dict]] = {}
    for event in batch:
        pending.setdefault(event["subject_id"], []).append(dict(event))

    ordered: list[dict] = []
    for subject, events in pending.items():
        events.sort(key=lambda e: (datetime.fromisoformat(e["occurred_at"]), e["event_id"]))
        version = store.next_version(subject)
        for event in events:
            event["version"] = version
            version += 1
            ordered.append(event)
    return ordered


def ingest_batch(store: EventStore, batch: list[dict]) -> IngestReport:
    report = IngestReport()
    seen_ids: set[str] = set()
    seen_receipts: set[tuple] = {
        receipt_fingerprint(e) for e in store.all_events() if is_receipt(e)
    }

    # 第一轮：校验与批内/库内去重
    fresh: list[dict] = []
    for raw in batch:
        eid = raw.get("event_id", "<missing>")
        errors = validate_event(raw)
        if errors:
            report.rejected.append({"event_id": eid, "errors": errors})
            continue
        if eid in seen_ids or store.get(eid) is not None:
            report.duplicates.append(eid)
            continue
        if is_receipt(raw):
            fp = receipt_fingerprint(raw)
            if fp in seen_receipts:
                report.duplicates.append(eid)
                continue
            seen_receipts.add(fp)
        seen_ids.add(eid)
        fresh.append(raw)

    # 第二轮：乱序重排后顺序追加
    for event in _assign_versions(fresh, store):
        try:
            store.append(event)
            report.accepted.append(event["event_id"])
        except (ConflictError, DomainError) as exc:
            report.rejected.append({"event_id": event["event_id"], "errors": [str(exc)]})

    return report
