"""订单履约投影：从订单事件流还原承诺、价格、付款与履约状态。

关键不变量：
- 订单生效（PLAN_FROZEN）后，冻结报价不可改写；后续价格变化只能以
  PRICE_CHANGED 追加，且必须区分平台自动跟价（PLATFORM_AUTO）与
  商家手工调价（MERCHANT_MANUAL）以明确责任；
- 房型降标（ROOM_DOWNGRADED）、临时拒住（STAY_REFUSED）、普通取消
  （ORDER_CANCELLED）是三种不同状态，互不混用；拒住后的强制取消
  （FORCE_CANCELLED）是拒住的后续，而非普通取消；
- 合同与退改规则按版本追加，旧版本保留可查。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain import DomainError, parse_ts


@dataclass(frozen=True)
class Quote:
    channel: str
    room_type: str
    price: float
    currency: str
    captured_at: str


@dataclass(frozen=True)
class PriceChange:
    channel: str
    room_type: str
    old_price: float
    new_price: float
    actor: str  # PLATFORM_AUTO / MERCHANT_MANUAL，调价责任归属
    occurred_at: str


@dataclass(frozen=True)
class Payment:
    payment_id: str
    amount: float
    currency: str
    method: str
    occurred_at: str


@dataclass(frozen=True)
class ContractVersion:
    contract_version: int
    clauses_digest: str
    occurred_at: str


@dataclass(frozen=True)
class PolicyVersion:
    policy_version: int
    cancel_rules: str
    occurred_at: str


@dataclass
class OrderState:
    order_id: str
    quotes: list[Quote] = field(default_factory=list)
    frozen_quote: Quote | None = None
    plan: dict | None = None  # 生效时的房型/星级/设施/套餐拆分承诺
    price_changes: list[PriceChange] = field(default_factory=list)
    contracts: list[ContractVersion] = field(default_factory=list)
    policies: list[PolicyVersion] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    lifecycle: str = "ACTIVE"  # ACTIVE / CANCELLED
    incident: str | None = None  # ROOM_DOWNGRADE / STAY_REFUSAL / FORCE_CANCELLED / CANCELLED
    incident_detail: dict | None = None
    checkin: dict | None = None
    appeals: list[dict] = field(default_factory=list)
    party_actions: list[dict] = field(default_factory=list)

    @property
    def total_paid(self) -> float:
        return sum(p.amount for p in self.payments)

    @property
    def price_difference(self) -> float | None:
        """实付与冻结报价差额（差价申诉的基准）。未生效或无付款时为 None。"""
        if self.frozen_quote is None or not self.payments:
            return None
        return round(self.total_paid - self.frozen_quote.price, 2)

    def price_changes_by(self, actor: str) -> list[PriceChange]:
        """按责任方筛选调价记录（平台自动跟价 vs 商家手工调价）。"""
        return [c for c in self.price_changes if c.actor == actor]


class OrderProjector:
    """把订单事件流折叠为 OrderState；违反不变量时抛 DomainError。"""

    def project(self, events: list[dict]) -> OrderState:
        state: OrderState | None = None
        for event in events:
            if state is None:
                state = OrderState(order_id=event["subject_id"])
            self._apply(state, event)
        if state is None:
            raise DomainError("订单没有事件，无法投影")
        return state

    # ------------------------------------------------------------------

    def _apply(self, state: OrderState, event: dict) -> None:
        kind = event["kind"]
        payload = event.get("payload", {})
        handler = getattr(self, f"_on_{kind.lower()}", None)
        if handler is None:
            return  # 非订单事件（案件/材料）由各自投影处理
        if state.lifecycle == "CANCELLED" and kind not in ("PAYMENT_RECORDED", "PARTY_ACTION_RECORDED", "PRICE_APPEAL_FILED"):
            raise DomainError(f"订单 {state.order_id} 已取消，拒绝后续事件 {kind}")
        handler(state, payload, event)

    def _on_quote_snapshotted(self, state: OrderState, payload: dict, event: dict) -> None:
        quote = Quote(
            channel=payload["channel"],
            room_type=payload["room_type"],
            price=float(payload["price"]),
            currency=payload["currency"],
            captured_at=payload["captured_at"],
        )
        # 同一渠道同一房型的报价快照不可改写：重复快照必须内容一致
        for existing in state.quotes:
            if existing.channel == quote.channel and existing.room_type == quote.room_type and existing != quote:
                raise DomainError(
                    f"渠道 {quote.channel} 房型 {quote.room_type} 的报价快照已存在且内容不同，拒绝改写"
                )
        if quote not in state.quotes:
            state.quotes.append(quote)

    def _on_plan_frozen(self, state: OrderState, payload: dict, event: dict) -> None:
        if state.frozen_quote is not None:
            raise DomainError(f"订单 {state.order_id} 已生效，冻结报价不可改写")
        matched = [q for q in state.quotes if q.channel == payload.get("channel") and q.room_type == payload["room_type"]]
        if payload.get("channel") and not matched:
            raise DomainError("冻结报价必须来自已留存的渠道报价快照")
        base = matched[0] if matched else None
        state.frozen_quote = Quote(
            channel=payload.get("channel", base.channel if base else "DIRECT"),
            room_type=payload["room_type"],
            price=float(payload["total_price"]),
            currency=payload["currency"],
            captured_at=event["occurred_at"],
        )
        state.plan = {
            "room_type": payload["room_type"],
            "star_level": payload["star_level"],
            "facilities": list(payload["facilities"]),
            "package_items": list(payload["package_items"]),
            "frozen_at": event["occurred_at"],
        }

    def _on_price_changed(self, state: OrderState, payload: dict, event: dict) -> None:
        if state.frozen_quote is None:
            raise DomainError("订单未生效，不存在可调价的冻结报价")
        state.price_changes.append(
            PriceChange(
                channel=payload["channel"],
                room_type=payload["room_type"],
                old_price=float(payload["old_price"]),
                new_price=float(payload["new_price"]),
                actor=payload["actor"],
                occurred_at=event["occurred_at"],
            )
        )

    def _on_contract_published(self, state: OrderState, payload: dict, event: dict) -> None:
        version = int(payload["contract_version"])
        if any(c.contract_version == version for c in state.contracts):
            raise DomainError(f"合同版本 v{version} 已存在，只能追加新版本")
        state.contracts.append(
            ContractVersion(version, payload["clauses_digest"], event["occurred_at"])
        )
        state.contracts.sort(key=lambda c: c.contract_version)

    def _on_policy_updated(self, state: OrderState, payload: dict, event: dict) -> None:
        version = int(payload["policy_version"])
        if any(p.policy_version == version for p in state.policies):
            raise DomainError(f"退改规则版本 v{version} 已存在，只能追加新版本")
        state.policies.append(
            PolicyVersion(version, payload["cancel_rules"], event["occurred_at"])
        )
        state.policies.sort(key=lambda p: p.policy_version)

    def _on_payment_recorded(self, state: OrderState, payload: dict, event: dict) -> None:
        if any(p.payment_id == payload["payment_id"] for p in state.payments):
            raise DomainError(f"支付流水 {payload['payment_id']} 重复")
        state.payments.append(
            Payment(
                payment_id=payload["payment_id"],
                amount=float(payload["amount"]),
                currency=payload["currency"],
                method=payload["method"],
                occurred_at=event["occurred_at"],
            )
        )

    def _on_checkin_recorded(self, state: OrderState, payload: dict, event: dict) -> None:
        if state.checkin is not None:
            raise DomainError("入住实况已记录，如需补充请走材料版本追加")
        state.checkin = {
            "actual_room_type": payload["actual_room_type"],
            "actual_star_level": payload["actual_star_level"],
            "facilities_observed": list(payload["facilities_observed"]),
            "occurred_at": event["occurred_at"],
        }

    def _on_room_downgraded(self, state: OrderState, payload: dict, event: dict) -> None:
        self._ensure_no_incident(state, "ROOM_DOWNGRADE")
        state.incident = "ROOM_DOWNGRADE"
        state.incident_detail = {
            "promised_room_type": payload["promised_room_type"],
            "actual_room_type": payload["actual_room_type"],
            "promised_star_level": payload["promised_star_level"],
            "actual_star_level": payload["actual_star_level"],
            "occurred_at": event["occurred_at"],
        }

    def _on_stay_refused(self, state: OrderState, payload: dict, event: dict) -> None:
        self._ensure_no_incident(state, "STAY_REFUSAL")
        state.incident = "STAY_REFUSAL"
        state.incident_detail = {"reason": payload["reason"], "occurred_at": event["occurred_at"]}

    def _on_order_cancelled(self, state: OrderState, payload: dict, event: dict) -> None:
        mode = payload["mode"]
        if state.incident == "STAY_REFUSAL":
            # 拒住之后的取消是强制取消的后续，沿用拒住责任，不记为普通取消
            state.incident = "FORCE_CANCELLED"
            state.incident_detail = {
                **(state.incident_detail or {}),
                "force_cancelled_at": event["occurred_at"],
            }
        else:
            self._ensure_no_incident(state, "CANCELLED")
            state.incident = "CANCELLED"
            state.incident_detail = {"mode": mode, "occurred_at": event["occurred_at"]}
        state.lifecycle = "CANCELLED"

    def _on_price_appeal_filed(self, state: OrderState, payload: dict, event: dict) -> None:
        if any(a["appeal_id"] == payload["appeal_id"] for a in state.appeals):
            raise DomainError(f"差价申诉 {payload['appeal_id']} 重复")
        state.appeals.append(
            {
                "appeal_id": payload["appeal_id"],
                "claimed_difference": float(payload["claimed_difference"]),
                "currency": payload["currency"],
                "occurred_at": event["occurred_at"],
            }
        )

    def _on_party_action_recorded(self, state: OrderState, payload: dict, event: dict) -> None:
        state.party_actions.append(
            {
                "party": payload["party"],
                "action": payload["action"],
                "detail": payload.get("detail"),
                "occurred_at": event["occurred_at"],
            }
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_no_incident(state: OrderState, incoming: str) -> None:
        if state.incident is not None:
            raise DomainError(
                f"订单 {state.order_id} 已处于 {state.incident} 状态，拒绝叠加 {incoming}："
                "降标、拒住与普通取消不得混为同一状态"
            )


def project_order(events: list[dict]) -> OrderState:
    return OrderProjector().project(events)
