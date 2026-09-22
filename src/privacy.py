"""公开页面投影：只展示维权所必需的最少个人信息。

- 个人标识一律脱敏（姓名、手机、证件号）。
- 证据仅放行 SUBMITTED 且密级 PUBLIC 的材料；DRAFT/WITHDRAWN 不展示，
  HELD（卷宗留置）与 INTERNAL/RESTRICTED 材料不对公开页面披露。
- 订单只公开履约判定所需事实：渠道、房型承诺、冻结价、实际履约状态与责任方，
  不公开支付凭证细节、合同全文等高敏内容。
"""
import re
from dataclasses import dataclass, field

from . import catalog as c


def mask_name(name: str | None) -> str | None:
    if not name:
        return None
    if len(name) == 1:
        return name
    return name[0] + "*" * (len(name) - 1)


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return "***"
    return digits[:3] + "****" + digits[-4:]


def mask_id_card(id_no: str | None) -> str | None:
    if not id_no:
        return None
    if len(id_no) <= 6:
        return "*" * len(id_no)
    return id_no[:3] + "*" * (len(id_no) - 6) + id_no[-3:]


_PII_MASKERS = {
    "name": mask_name,
    "phone": mask_phone,
    "id_card": mask_id_card,
}


def mask_pii(pii: dict) -> dict:
    """对已知个人字段按类型脱敏，未知字段默认整体遮蔽。"""
    out = {}
    for key, value in pii.items():
        masker = _PII_MASKERS.get(key)
        out[key] = masker(value) if masker else "***"
    return out


@dataclass
class PublicCaseView:
    case_ref: str
    consumer: dict
    channel: str | None
    promised_room_type: str | None
    promised_star_class: int | None
    frozen_price: float | None
    price_delta: float | None
    liable_party: str | None
    fulfillment_state: str | None
    mediation_outcome: str | None
    referred_to_authority: bool
    downgrade_gaps: list = field(default_factory=list)
    public_evidence: list = field(default_factory=list)
    withheld_count: int = 0


def build_public_view(case_view, consumer_pii: dict | None = None) -> PublicCaseView:
    """从案件负责人视图收敛出公开视图。case_view 来自 cases.build_case_view。"""
    order = case_view.order
    promised = order.promises[-1] if order and order.promises else None
    channel = None
    if order and order.frozen_quote_ref:
        channel = order.quotes[order.frozen_quote_ref]["channel"]

    public_evidence, withheld_count = [], 0
    for ref, item in case_view.evidence.items():
        if item.is_publicly_visible():
            latest = item.versions[-1]
            public_evidence.append({
                "evidence_ref": ref,
                "evidence_type": item.evidence_type,
                "doc_version": latest.doc_version,
                # 公开材料也不公开原始文件名之外的身份线索
                "filename": latest.filename,
            })
        else:
            withheld_count += 1

    mediation = case_view.mediations[-1]["outcome"] if case_view.mediations else None

    return PublicCaseView(
        case_ref=case_view.case_ref,
        consumer=mask_pii(consumer_pii or {}),
        channel=channel,
        promised_room_type=promised["room_type"] if promised else None,
        promised_star_class=promised["star_class"] if promised else None,
        frozen_price=order.frozen_price() if order else None,
        price_delta=order.price_delta() if order else None,
        liable_party=order.liable_party() if order else None,
        fulfillment_state=order.fulfillment_state if order else None,
        downgrade_gaps=order.downgrade_gaps() if order else [],
        mediation_outcome=mediation,
        referred_to_authority=case_view.referral is not None,
        public_evidence=public_evidence,
        withheld_count=withheld_count,
    )
