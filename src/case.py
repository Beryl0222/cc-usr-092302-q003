"""案件链：从一条投诉还原承诺、付款、履约与处置全过程。

承办人视图（handler_view）保留完整链路；公开页面（public_view）只展示
维权所需的最少个人信息：消费者化名脱敏、主体标识打码、撤回材料不出现、
CONFIDENTIAL 材料不公开。
"""

from __future__ import annotations

from src.domain import DomainError, mask_middle, mask_name
from src.evidence import EvidenceVault
from src.order import OrderProjector, OrderState


class CaseRecord:
    def __init__(self, case_id: str, order_id: str, consumer_alias: str, claims: list[str]) -> None:
        self.case_id = case_id
        self.order_id = order_id
        self.consumer_alias = consumer_alias
        self.claims = list(claims)
        self.status = "OPEN"  # OPEN / MEDIATION / REFERRED / CLOSED
        self.mediation: dict | None = None
        self.referral: dict | None = None


class CaseRegistry:
    """跨聚合投影：订单流 + 案件流 + 证据卷 → 案件链。"""

    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}
        self._order_events: dict[str, list[dict]] = {}
        self.vault = EvidenceVault()

    def apply(self, event: dict) -> None:
        kind = event["kind"]
        payload = event.get("payload", {})
        if kind == "COMPLAINT_FILED":
            self._on_complaint(event["subject_id"], payload)
        elif kind == "MEDIATION_RESULT_RECORDED":
            self._require(event["subject_id"]).mediation = {
                "outcome": payload["outcome"],
                "compensation": payload.get("compensation"),
                "currency": payload.get("currency"),
                "occurred_at": event["occurred_at"],
            }
            self._cases[event["subject_id"]].status = "CLOSED"
        elif kind == "REGULATORY_REFERRAL_MADE":
            record = self._require(event["subject_id"])
            record.referral = {
                "authority": payload["authority"],
                "docket_id": payload["docket_id"],
                "occurred_at": event["occurred_at"],
            }
            record.status = "REFERRED"
        elif kind.startswith("EVIDENCE_"):
            self.vault.apply(event)
        else:
            # 订单事件：缓存供案件链投影
            self._order_events.setdefault(event["subject_id"], []).append(event)

    # ------------------------------------------------------------------
    # 案件链
    # ------------------------------------------------------------------

    def order_state(self, order_id: str) -> OrderState:
        events = self._order_events.get(order_id)
        if not events:
            raise DomainError(f"订单 {order_id} 没有事件")
        return OrderProjector().project(events)

    def chain(self, case_id: str) -> dict:
        """承办人视角的完整链：承诺 → 付款 → 履约 → 处置。"""
        record = self._require(case_id)
        order = self.order_state(record.order_id)
        return {
            "case_id": record.case_id,
            "order_id": record.order_id,
            "status": record.status,
            "consumer_alias": record.consumer_alias,
            "claims": list(record.claims),
            "promise": {
                "frozen_quote": order.frozen_quote,
                "plan": order.plan,
                "quotes": list(order.quotes),
                "contracts": list(order.contracts),
                "policies": list(order.policies),
                "price_changes": list(order.price_changes),
            },
            "payment": {
                "payments": list(order.payments),
                "total_paid": order.total_paid,
                "price_difference": order.price_difference,
            },
            "fulfillment": {
                "checkin": order.checkin,
                "incident": order.incident,
                "incident_detail": order.incident_detail,
                "party_actions": list(order.party_actions),
            },
            "disposition": {
                "appeals": list(order.appeals),
                "mediation": record.mediation,
                "referral": record.referral,
            },
            "materials": self.vault.handler_metadata(),
        }

    def public_view(self, case_id: str) -> dict:
        """公开页面：只保留维权所需的最少个人信息。"""
        record = self._require(case_id)
        order = self.order_state(record.order_id)
        view: dict = {
            "case_id": mask_middle(record.case_id),
            "status": record.status,
            "consumer": mask_name(record.consumer_alias),
            "claims": list(record.claims),
            "promise": {
                "room_type": order.plan["room_type"] if order.plan else None,
                "star_level": order.plan["star_level"] if order.plan else None,
                "frozen_price": order.frozen_quote.price if order.frozen_quote else None,
                "currency": order.frozen_quote.currency if order.frozen_quote else None,
            },
            "payment": {
                "total_paid": order.total_paid,
                "price_difference": order.price_difference,
            },
            "fulfillment": {
                "incident": order.incident,
                "actual_room_type": (order.checkin or {}).get("actual_room_type"),
                "actual_star_level": (order.checkin or {}).get("actual_star_level"),
            },
            "disposition": {
                "mediation_outcome": (record.mediation or {}).get("outcome"),
                "referred": record.referral is not None,
            },
            # 撤回材料已被 public_metadata 过滤；CONFIDENTIAL 不出现
            "materials": [
                m for m in self.vault.public_metadata()
                if self.vault.get(m["material_id"]).sensitivity != "CONFIDENTIAL"
            ],
        }
        return view

    # ------------------------------------------------------------------

    def _on_complaint(self, case_id: str, payload: dict) -> None:
        if case_id in self._cases:
            raise DomainError(f"案件 {case_id} 已存在")
        self._cases[case_id] = CaseRecord(
            case_id=case_id,
            order_id=payload["order_id"],
            consumer_alias=payload["consumer_alias"],
            claims=list(payload["claims"]),
        )

    def _require(self, case_id: str) -> CaseRecord:
        try:
            return self._cases[case_id]
        except KeyError:
            raise DomainError(f"案件 {case_id} 不存在") from None
