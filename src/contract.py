"""事件信封合同：所有进入系统的事件必须满足的结构性约束。

校验分两层：
- validate(record)：信封级（基线接口，返回缺失字段名列表，保持兼容）；
- validate_event(record)：完整校验（信封 + 类型 + payload 必填 + 取值域），
  返回错误描述列表，空列表表示通过。

事件一旦写入即不可改写；本合同是各服务共享的唯一权威定义。
"""

from __future__ import annotations

from datetime import datetime

from src.domain import (
    ACTOR_ROLES,
    CANCEL_MODES,
    CASE_EVENT_KINDS,
    CHANNELS,
    EVENT_KINDS,
    INCIDENT_CODES,
    MATERIAL_EVENT_KINDS,
    ORDER_EVENT_KINDS,
    ORIGIN_METHODS,
    PRICE_CHANGE_ACTORS,
    SENSITIVITY_LEVELS,
)

REQUIRED = ("event_id", "kind", "occurred_at", "subject_id", "version")

# 每种事件类型的 payload 必填字段
PAYLOAD_REQUIRED: dict[str, tuple[str, ...]] = {
    "QUOTE_SNAPSHOTTED": ("channel", "room_type", "price", "currency", "captured_at"),
    "PLAN_FROZEN": ("room_type", "star_level", "facilities", "package_items", "total_price", "currency"),
    "CONTRACT_PUBLISHED": ("contract_version", "clauses_digest"),
    "PAYMENT_RECORDED": ("payment_id", "amount", "currency", "method"),
    "PRICE_CHANGED": ("channel", "room_type", "old_price", "new_price", "actor"),
    "POLICY_UPDATED": ("policy_version", "cancel_rules"),
    "CHECKIN_RECORDED": ("actual_room_type", "actual_star_level", "facilities_observed"),
    "ROOM_DOWNGRADED": ("promised_room_type", "actual_room_type", "promised_star_level", "actual_star_level"),
    "STAY_REFUSED": ("reason",),
    "ORDER_CANCELLED": ("mode",),
    "PRICE_APPEAL_FILED": ("appeal_id", "claimed_difference", "currency"),
    "PARTY_ACTION_RECORDED": ("party", "action"),
    "COMPLAINT_FILED": ("order_id", "consumer_alias", "claims"),
    "MEDIATION_RESULT_RECORDED": ("outcome",),
    "REGULATORY_REFERRAL_MADE": ("authority", "docket_id"),
    "EVIDENCE_REGISTERED": ("material_type", "title", "sensitivity", "origin", "hash", "submitted"),
    "EVIDENCE_VERSION_ADDED": ("hash",),
    "EVIDENCE_SUBMITTED": (),
    "EVIDENCE_WITHDRAWN": (),
    "EVIDENCE_DOCKETED": ("docket_id",),
}

# payload 中取值受限的字段
_ENUM_FIELDS = {
    "channel": CHANNELS,
    "actor": PRICE_CHANGE_ACTORS,
    "mode": CANCEL_MODES,
    "party": ACTOR_ROLES,
    "sensitivity": SENSITIVITY_LEVELS,
    "incident_code": INCIDENT_CODES,
}

# 每种事件类型的主体类型，用于跨聚合引用检查
SUBJECT_TYPE = {
    **{kind: "order" for kind in ORDER_EVENT_KINDS},
    **{kind: "case" for kind in CASE_EVENT_KINDS},
    **{kind: "material" for kind in MATERIAL_EVENT_KINDS},
}


def validate(record: dict) -> list[str]:
    """信封级校验：返回缺失的必填字段名（基线接口，保持兼容）。"""
    return [name for name in REQUIRED if name not in record]


def _check_origin(origin: object) -> list[str]:
    if not isinstance(origin, dict):
        return ["payload.origin 必须是对象"]
    errors = [f"payload.origin 缺少字段 {name}" for name in ("method", "captured_at") if name not in origin]
    if "method" in origin and origin["method"] not in ORIGIN_METHODS:
        errors.append(f"payload.origin.method 非法: {origin['method']!r}")
    if "captured_at" in origin and isinstance(origin["captured_at"], str):
        try:
            datetime.fromisoformat(origin["captured_at"])
        except ValueError:
            errors.append(f"payload.origin.captured_at 非法: {origin['captured_at']!r}")
    return errors


def validate_event(record: dict) -> list[str]:
    """完整校验：信封 + 类型 + payload 必填 + 取值域。返回错误描述列表。"""
    errors: list[str] = []

    missing = validate(record)
    errors.extend(f"缺少字段 {name}" for name in missing)

    kind = record.get("kind")
    if kind is not None and kind not in EVENT_KINDS:
        errors.append(f"未知事件类型: {kind!r}")

    occurred_at = record.get("occurred_at")
    if isinstance(occurred_at, str):
        try:
            parsed = datetime.fromisoformat(occurred_at)
            if parsed.tzinfo is None:
                errors.append("occurred_at 缺少时区")
        except ValueError:
            errors.append(f"occurred_at 非法: {occurred_at!r}")
    elif "occurred_at" in record:
        errors.append("occurred_at 必须是 ISO 8601 字符串")

    version = record.get("version")
    if "version" in record and (not isinstance(version, int) or isinstance(version, bool) or version < 1):
        errors.append("version 必须是 >= 1 的整数")

    actor = record.get("actor")
    if actor is not None and actor not in ACTOR_ROLES:
        errors.append(f"actor 非法: {actor!r}")

    payload = record.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        errors.append("payload 必须是对象")
        return errors

    if kind in PAYLOAD_REQUIRED:
        errors.extend(f"payload 缺少字段 {name}" for name in PAYLOAD_REQUIRED[kind] if name not in payload)

    for field, allowed in _ENUM_FIELDS.items():
        if field in payload and payload[field] not in allowed:
            errors.append(f"payload.{field} 非法: {payload[field]!r}")

    if kind == "EVIDENCE_REGISTERED" and "origin" in payload:
        errors.extend(_check_origin(payload["origin"]))

    return errors
