"""测试辅助：事件构造与场景加载。"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "fixtures"


def make_event(
    event_id: str,
    kind: str,
    subject_id: str,
    occurred_at: str,
    version: int,
    payload: dict | None = None,
    actor: str | None = None,
) -> dict:
    event = {
        "event_id": event_id,
        "kind": kind,
        "occurred_at": occurred_at,
        "subject_id": subject_id,
        "version": version,
        "payload": payload or {},
    }
    if actor is not None:
        event["actor"] = actor
    return event


def load_scenario() -> list[dict]:
    return json.loads((FIXTURES / "scenario.json").read_text(encoding="utf-8"))
