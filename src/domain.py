"""共享领域定义：枚举、异常与通用工具。

各投影（订单、证据卷、案件链）与事件合同共用这里的常量，
保证事件 payload 的取值域只有一份权威定义。
"""

from __future__ import annotations

import hashlib
from datetime import datetime

# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class DomainError(Exception):
    """违反取证领域不变量时抛出（调用方数据或时序问题，均可恢复）。"""


class ConflictError(DomainError):
    """同一标识下出现内容不一致的记录（如重复 event_id 载荷不同）。"""


# ---------------------------------------------------------------------------
# 事件类型
# ---------------------------------------------------------------------------

EVENT_KINDS = (
    # 承诺侧：报价、套餐、合同、退改
    "QUOTE_SNAPSHOTTED",
    "PLAN_FROZEN",
    "CONTRACT_PUBLISHED",
    "PAYMENT_RECORDED",
    "PRICE_CHANGED",
    "POLICY_UPDATED",
    # 履约侧：入住实况与异常
    "CHECKIN_RECORDED",
    "ROOM_DOWNGRADED",
    "STAY_REFUSED",
    "ORDER_CANCELLED",
    # 处置侧：申诉、调解、监管
    "PRICE_APPEAL_FILED",
    "PARTY_ACTION_RECORDED",
    "COMPLAINT_FILED",
    "MEDIATION_RESULT_RECORDED",
    "REGULATORY_REFERRAL_MADE",
    # 证据材料生命周期
    "EVIDENCE_REGISTERED",
    "EVIDENCE_VERSION_ADDED",
    "EVIDENCE_SUBMITTED",
    "EVIDENCE_WITHDRAWN",
    "EVIDENCE_DOCKETED",
)

# 事件主体类型：决定 subject_id 指向哪类聚合
ORDER_EVENT_KINDS = (
    "QUOTE_SNAPSHOTTED",
    "PLAN_FROZEN",
    "CONTRACT_PUBLISHED",
    "PAYMENT_RECORDED",
    "PRICE_CHANGED",
    "POLICY_UPDATED",
    "CHECKIN_RECORDED",
    "ROOM_DOWNGRADED",
    "STAY_REFUSED",
    "ORDER_CANCELLED",
    "PRICE_APPEAL_FILED",
    "PARTY_ACTION_RECORDED",
)

CASE_EVENT_KINDS = (
    "COMPLAINT_FILED",
    "MEDIATION_RESULT_RECORDED",
    "REGULATORY_REFERRAL_MADE",
)

MATERIAL_EVENT_KINDS = (
    "EVIDENCE_REGISTERED",
    "EVIDENCE_VERSION_ADDED",
    "EVIDENCE_SUBMITTED",
    "EVIDENCE_WITHDRAWN",
    "EVIDENCE_DOCKETED",
)

# ---------------------------------------------------------------------------
# 取值域
# ---------------------------------------------------------------------------

CHANNELS = ("OTA", "DIRECT", "AGENT", "CUSTOM_TOUR")

ACTOR_ROLES = ("CONSUMER", "MERCHANT", "PLATFORM", "MEDIATOR", "REGULATOR", "SYSTEM")

# 调价责任：平台自动跟价与商家手工调价必须区分
PRICE_CHANGE_ACTORS = ("PLATFORM_AUTO", "MERCHANT_MANUAL")

# 普通取消模式：拒住后强制取消与商家取消另有专属事件，不能混用
CANCEL_MODES = ("CONSUMER", "MERCHANT")

# 材料来源校验方式
ORIGIN_METHODS = ("SCREENSHOT", "UPLOAD", "CAMERA", "EMAIL")

# 敏感字段分级
SENSITIVITY_LEVELS = ("PUBLIC", "PROTECTED", "CONFIDENTIAL")

# 材料状态
MATERIAL_STATES = ("DRAFT", "SUBMITTED", "WITHDRAWN", "DOCKETED")

# 订单履约异常（互斥，且与普通取消区分）
INCIDENT_CODES = ("ROOM_DOWNGRADE", "STAY_REFUSAL", "FORCE_CANCELLED", "CANCELLED")

# 订单生命周期
ORDER_LIFECYCLES = ("ACTIVE", "CANCELLED")

# 案件状态
CASE_STATUSES = ("OPEN", "MEDIATION", "REFERRED", "CLOSED")

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def parse_ts(value: str) -> datetime:
    """解析 ISO 8601 时间戳，必须带时区。"""
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise DomainError(f"非法时间戳: {value!r}") from exc
    if ts.tzinfo is None:
        raise DomainError(f"时间戳缺少时区: {value!r}")
    return ts


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mask_middle(value: str, keep: int = 2) -> str:
    """通用中段打码：保留首尾各 keep 位，中间以 * 代替。"""
    text = str(value)
    if len(text) <= keep * 2:
        return "*" * len(text)
    return f"{text[:keep]}{'*' * (len(text) - keep * 2)}{text[-keep:]}"


def mask_name(name: str) -> str:
    """姓名脱敏：仅保留首字，长度不公开。"""
    text = str(name)
    return text[0] + "*" if text else "*"


def mask_phone(phone: str) -> str:
    """手机号脱敏：保留前三后二。"""
    text = str(phone)
    if len(text) <= 5:
        return "*" * len(text)
    return f"{text[:3]}{'*' * (len(text) - 5)}{text[-2:]}"
