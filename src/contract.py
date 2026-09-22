"""事件信封与载荷校验。

信封（event_id/kind/occurred_at/subject_id/version）为跨参与方共同约定；
载荷按 src.catalog 中的事件目录逐类校验。
"""
from datetime import datetime

from . import catalog
from .errors import ValidationError

REQUIRED = ("event_id", "kind", "occurred_at", "subject_id", "version")

# 各枚举字段允许的取值
_ENUM_FIELDS = {
    "channel": catalog.ALL_CHANNELS,
    "actor": catalog.ALL_ACTORS,
    "change_type": catalog.PRICE_CHANGE_TYPES,
    "fulfillment_state": catalog.FULFILLMENT_STATES,
    "cancel_reason": catalog.CANCEL_REASONS,
    "evidence_type": catalog.EVIDENCE_TYPES,
    "sensitivity": catalog.SENSITIVITY_LEVELS,
    "state": catalog.EVIDENCE_STATES,
}


def validate(record: dict) -> list[str]:
    """仅校验信封必填项（保持基线兼容）。"""
    return [name for name in REQUIRED if name not in record]


def _parse_ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError([f"occurred_at 不是合法 ISO-8601 时间: {value!r}"])


def validate_event(record: dict) -> list[str]:
    """完整校验一条事件：信封 + 目录载荷 + 枚举。返回错误列表（空列表即通过）。"""
    errors = validate(record)
    if errors:
        return [f"缺少信封字段: {name}" for name in errors]

    kind = record["kind"]
    if kind not in catalog.PAYLOAD_SPEC:
        errors.append(f"未知事件 kind: {kind}")

    if not isinstance(record["version"], int) or isinstance(record["version"], bool) \
            or record["version"] < 1:
        errors.append("version 必须为 >=1 的整数")

    if not isinstance(record["event_id"], str) or not record["event_id"]:
        errors.append("event_id 必须为非空字符串")
    if not isinstance(record["subject_id"], str) or not record["subject_id"]:
        errors.append("subject_id 必须为非空字符串")

    try:
        _parse_ts(record["occurred_at"])
    except ValidationError as exc:
        errors.extend(exc.errors)

    payload = record.get("payload", {})
    if not isinstance(payload, dict):
        errors.append("payload 必须为对象")
        return errors

    if kind in catalog.PAYLOAD_SPEC:
        required_fields, optional_fields = catalog.PAYLOAD_SPEC[kind]
        for field in required_fields:
            if field not in payload:
                errors.append(f"{kind} 载荷缺少必需字段: {field}")
        allowed = set(required_fields) | set(optional_fields)
        for field in payload:
            if field not in allowed:
                errors.append(f"{kind} 载荷含未声明字段: {field}")
        for field, allowed_values in _ENUM_FIELDS.items():
            if field in payload and payload[field] not in allowed_values:
                errors.append(
                    f"{kind}.{field} 取值非法: {payload[field]!r}，允许 {allowed_values}"
                )

    return errors


def require_valid(record: dict) -> None:
    """校验不通过时抛出 ValidationError。"""
    errors = validate_event(record)
    if errors:
        raise ValidationError(errors)
