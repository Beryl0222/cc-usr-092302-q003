"""案件视图：负责人可从一条投诉还原“承诺 → 付款 → 履约 → 处置”完整链。

案件事件可以引用订单主题（CASE_OPENED.order_subject_id）；构建时把订单事件流、
证据登记与案件处置事件合并为一条按时间排列的可追溯时间线。
"""
from dataclasses import dataclass, field
from datetime import datetime

from . import catalog as c
from .evidence import build_registry
from .orders import build_order


@dataclass
class CaseView:
    case_ref: str
    order_subject_id: str | None
    opened_at: str | None = None
    appeal: dict | None = None
    order: object | None = None
    evidence: dict = field(default_factory=dict)
    mediations: list[dict] = field(default_factory=list)
    referral: dict | None = None
    closure: dict | None = None
    timeline: list[dict] = field(default_factory=list)

    def held_dockets(self) -> list[dict]:
        return [
            {"evidence_ref": ref, **(item.held_by or {})}
            for ref, item in self.evidence.items() if item.state == c.EV_HELD
        ]

    def chain(self) -> dict:
        """四段式责任链视图。"""
        order = self.order
        return {
            "commitment": {
                "quotes": list(order.quotes.values()) if order else [],
                "frozen_quote_ref": order.frozen_quote_ref if order else None,
                "promises": order.promises if order else [],
                "package_components": order.package_components if order else {},
                "contract_versions": order.contract_versions if order else [],
            },
            "payment": {
                "payments": order.payments if order else [],
                "refunds": order.refunds if order else [],
                "policies": order.cancellation_policies if order else [],
            },
            "fulfillment": {
                "state": order.fulfillment_state if order else None,
                "actual": order.actual if order else None,
                "downgrade_gaps": order.downgrade_gaps() if order else [],
                "price_changes": [
                    {"occurred_at": ch.occurred_at, "change_type": ch.change_type,
                     "actor": ch.actor, "old": ch.old_price, "new": ch.new_price,
                     "reason": ch.reason}
                    for ch in (order.price_changes if order else [])
                ],
                "liable_party": order.liable_party() if order else None,
                "merchant_ops": order.merchant_ops if order else [],
                "platform_ops": order.platform_ops if order else [],
            },
            "disposition": {
                "appeal": self.appeal,
                "mediations": self.mediations,
                "referral": self.referral,
                "closure": self.closure,
                "held_dockets": self.held_dockets(),
            },
        }


def build_case_view(case_events: list[dict],
                    order_events: list[dict] | None = None,
                    evidence_events: list[dict] | None = None) -> CaseView:
    case_events = sorted(case_events,
                         key=lambda e: (datetime.fromisoformat(e["occurred_at"]), e["version"]))
    if not case_events:
        raise ValueError("案件至少需要一条 CASE_OPENED 事件")

    opened = next((e for e in case_events if e["kind"] == c.KIND_CASE_OPENED), None)
    if opened is None:
        raise ValueError("缺少 CASE_OPENED 事件")

    view = CaseView(case_ref=opened["payload"]["case_ref"],
                    order_subject_id=opened["payload"].get("order_subject_id"),
                    opened_at=opened["payload"]["opened_at"])

    for e in case_events:
        kind, p = e["kind"], e["payload"]
        if kind == c.KIND_PRICE_APPEAL:
            view.appeal = {
                "appeal_ref": p["appeal_ref"], "quote_ref": p["quote_ref"],
                "expected_amount": p["expected_amount"],
                "claimed_amount": p["claimed_amount"],
                "reason": p.get("reason"), "opened_at": p.get("opened_at"),
            }
        elif kind == c.KIND_CASE_MEDIATION:
            view.mediations.append({
                "mediated_at": p["mediated_at"], "outcome": p["outcome"],
                "award_amount": p.get("award_amount"),
                "currency": p.get("currency"), "note": p.get("note"),
            })
        elif kind == c.KIND_CASE_REFERRAL:
            view.referral = {
                "referred_at": p["referred_at"], "authority": p["authority"],
                "docket": p.get("docket"), "reason": p.get("reason"),
            }
        elif kind == c.KIND_CASE_CLOSED:
            view.closure = {
                "closed_at": p["closed_at"], "resolution": p["resolution"],
                "note": p.get("note"),
            }

    if order_events:
        view.order = build_order(view.order_subject_id or "<case-order>", order_events)
    if evidence_events:
        view.evidence = build_registry(evidence_events)

    # 合并时间线：订单事实 + 证据动作 + 案件处置
    merged: list[dict] = []
    for e in (order_events or []):
        merged.append({"at": e["occurred_at"], "stage": "order",
                       "kind": e["kind"], "payload": e["payload"]})
    for e in (evidence_events or []):
        merged.append({"at": e["occurred_at"], "stage": "evidence",
                       "kind": e["kind"], "payload": e["payload"]})
    for e in case_events:
        merged.append({"at": e["occurred_at"], "stage": "case",
                       "kind": e["kind"], "payload": e["payload"]})
    merged.sort(key=lambda x: x["at"])
    view.timeline = merged
    return view
