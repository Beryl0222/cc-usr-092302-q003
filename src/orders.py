"""订单履约聚合：从一条订单的事件流重建承诺、价格、付款与履约状态。

关键不变量：
1. 订单生效（QUOTE_FROZEN）后，原报价作为不可变快照保留；之后的价格变动
   只能追加 PRICE_CHANGED，不能改写 QUOTE_CAPTURED 的价格。
2. PRICE_CHANGED 区分责任：AUTO_MATCH（平台自动跟价）与 MANUAL（商家手工调价）。
3. 入住实况只能沿 正常 → 降标/拒住/取消 分流一次并锁定；
   降标、临住拒住、普通取消是三个互斥终态，不允许混用或互相改写。
4. 合同版本、退改规则只追加新版本，旧版仍在事件流中可追溯。
"""
from dataclasses import dataclass, field
from datetime import datetime

from . import catalog as c
from .errors import DomainError


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass
class PriceChange:
    occurred_at: str
    new_price: float
    change_type: str
    actor: str
    old_price: float | None = None
    reason: str | None = None


@dataclass
class OrderState:
    subject_id: str
    quotes: dict = field(default_factory=dict)        # quote_ref -> 快照（不可变）
    frozen_quote_ref: str | None = None
    frozen_at: str | None = None
    price_changes: list[PriceChange] = field(default_factory=list)
    promises: list[dict] = field(default_factory=list)
    package_components: dict = field(default_factory=dict)  # package_ref -> components
    contract_versions: list[dict] = field(default_factory=list)
    cancellation_policies: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    refunds: list[dict] = field(default_factory=list)
    fulfillment_state: str | None = None
    actual: dict | None = None
    checkin_at: str | None = None
    merchant_ops: list[dict] = field(default_factory=list)
    platform_ops: list[dict] = field(default_factory=list)

    # ---- 责任判定 ----
    def liable_party(self) -> str | None:
        """对生效后涨价的责任方：平台自动跟价 → 平台；商家手工 → 商家。"""
        if not self.price_changes:
            return None
        latest = self.price_changes[-1]
        if latest.change_type == c.PRICE_CHANGE_AUTO_MATCH:
            return c.ACTOR_PLATFORM_AUTO
        return c.ACTOR_MERCHANT

    def frozen_price(self) -> float | None:
        if self.frozen_quote_ref and self.frozen_quote_ref in self.quotes:
            return self.quotes[self.frozen_quote_ref]["price_amount"]
        return None

    def current_price(self) -> float | None:
        if self.price_changes:
            return self.price_changes[-1].new_price
        return self.frozen_price()

    def price_delta(self) -> float | None:
        if self.frozen_price() is None or self.current_price() is None:
            return None
        return round(self.current_price() - self.frozen_price(), 2)

    def downgrade_gaps(self) -> list[dict]:
        """对比最新房型承诺与实际入住：列出降标项。"""
        if self.fulfillment_state != c.FULFILLMENT_DOWNGRADED or not self.promises:
            return []
        promised = self.promises[-1]
        actual = self.actual or {}
        gaps = []
        if actual.get("actual_room_type") and actual["actual_room_type"] != promised["room_type"]:
            gaps.append({"field": "room_type",
                         "promised": promised["room_type"],
                         "actual": actual["actual_room_type"]})
        if actual.get("actual_star_class") and actual["actual_star_class"] < promised["star_class"]:
            gaps.append({"field": "star_class",
                         "promised": promised["star_class"],
                         "actual": actual["actual_star_class"]})
        promised_fac = set(promised.get("facilities", []))
        actual_fac = set(actual.get("actual_facilities", []))
        missing = sorted(promised_fac - actual_fac)
        if missing:
            gaps.append({"field": "facilities", "promised": sorted(promised_fac),
                         "actual": sorted(actual_fac), "missing": missing})
        return gaps


def build_order(subject_id: str, events: list[dict], *, raise_on_error: bool = True) -> OrderState:
    """按业务时间顺序回放事件，重建订单状态并执行不变量校验。"""
    state = OrderState(subject_id=subject_id)
    ordered = sorted(events, key=lambda e: (_ts(e["occurred_at"]), e["version"]))

    for e in ordered:
        kind, p, at = e["kind"], e["payload"], e["occurred_at"]
        try:
            if kind == c.KIND_QUOTE_CAPTURED:
                ref = p.get("quote_ref") or f"quote@{p['captured_at']}"
                if ref in state.quotes:
                    raise DomainError(f"报价快照 {ref} 已存在，渠道报价只能另存新快照")
                # 防御：即便事件流被旁路写入，也绝不允许改动已登记快照的价格
                state.quotes[ref] = {
                    "channel": p["channel"],
                    "room_type": p["room_type"],
                    "price_amount": p["price_amount"],
                    "currency": p["currency"],
                    "captured_at": p["captured_at"],
                    "facilities": list(p.get("facilities", [])),
                    "source_evidence_id": p.get("source_evidence_id"),
                }

            elif kind == c.KIND_QUOTE_FROZEN:
                ref = p["quote_ref"]
                if ref not in state.quotes:
                    raise DomainError(f"冻结报价 {ref} 前必须先登记 QUOTE_CAPTURED")
                if state.frozen_quote_ref is not None:
                    raise DomainError("订单报价只能冻结一次，生效后不得重新冻结/改价")
                state.frozen_quote_ref = ref
                state.frozen_at = at

            elif kind == c.KIND_PRICE_CHANGED:
                if state.frozen_quote_ref is None:
                    raise DomainError("订单生效前的价格差异应登记为新的渠道报价快照，而非 PRICE_CHANGED")
                ref = p["quote_ref"]
                if ref != state.frozen_quote_ref:
                    raise DomainError(
                        f"价格变动必须针对冻结报价 {state.frozen_quote_ref}，收到 {ref}；"
                        "其他渠道价格应登记为独立报价快照"
                    )
                # 责任方与变动类型必须一致：平台自动跟价只能由 PLATFORM_AUTO 发起
                if p["change_type"] == c.PRICE_CHANGE_AUTO_MATCH and p["actor"] != c.ACTOR_PLATFORM_AUTO:
                    raise DomainError("AUTO_MATCH 只能来自平台自动跟价 (PLATFORM_AUTO)")
                if p["change_type"] == c.PRICE_CHANGE_MANUAL and p["actor"] != c.ACTOR_MERCHANT:
                    raise DomainError("MANUAL 调价只能来自商家 (MERCHANT)")
                state.price_changes.append(PriceChange(
                    occurred_at=at,
                    new_price=p["new_price_amount"],
                    old_price=p.get("old_price_amount"),
                    change_type=p["change_type"],
                    actor=p["actor"],
                    reason=p.get("reason"),
                ))

            elif kind == c.KIND_ROOM_PROMISED:
                state.promises.append({
                    "room_type": p["room_type"],
                    "star_class": p["star_class"],
                    "facilities": list(p["facilities"]),
                    "promised_at": at,
                    "source_evidence_id": p.get("source_evidence_id"),
                })

            elif kind == c.KIND_PACKAGE_SPLIT:
                if not p["components"]:
                    raise DomainError("套餐拆分 components 不能为空")
                state.package_components[p["package_ref"]] = list(p["components"])

            elif kind == c.KIND_CONTRACT_VERSION:
                if any(v["doc_version"] == p["doc_version"] for v in state.contract_versions):
                    raise DomainError(f"合同版本 {p['doc_version']} 已存在，补充修订只能追加新版本")
                state.contract_versions.append({
                    "contract_ref": p["contract_ref"],
                    "doc_version": p["doc_version"],
                    "supersedes": p.get("supersedes_doc_version"),
                    "terms": dict(p["terms"]),
                    "at": at,
                    "source_evidence_id": p.get("source_evidence_id"),
                })

            elif kind == c.KIND_CANCELLATION_POLICY:
                if any(v["policy_version"] == p["policy_version"]
                       for v in state.cancellation_policies):
                    raise DomainError(f"退改规则版本 {p['policy_version']} 重复，只能追加")
                state.cancellation_policies.append({
                    "policy_version": p["policy_version"],
                    "rules": dict(p["rules"]),
                    "at": at,
                })

            elif kind == c.KIND_PAYMENT:
                state.payments.append({
                    "amount": p["amount"], "currency": p["currency"],
                    "paid_at": p["paid_at"], "method": p.get("method"),
                    "receipt_evidence_id": p.get("receipt_evidence_id"),
                })

            elif kind == c.KIND_PAYMENT_REFUND:
                state.refunds.append({
                    "amount": p["amount"], "currency": p["currency"],
                    "refunded_at": p["refunded_at"], "reason": p.get("reason"),
                })

            elif kind == c.KIND_CHECKIN_REPORTED:
                if state.fulfillment_state is not None:
                    raise DomainError(
                        f"履约状态已锁定为 {state.fulfillment_state}，"
                        "降标/拒住/普通取消互斥，不能再登记入住实况"
                    )
                fs = p["fulfillment_state"]
                if fs == c.FULFILLMENT_CANCELLED and not p.get("cancel_reason"):
                    raise DomainError("普通取消必须给出 cancel_reason")
                if fs in (c.FULFILLMENT_DOWNGRADED, c.FULFILLMENT_REFUSED_AT_CHECKIN) \
                        and p.get("cancel_reason"):
                    raise DomainError(f"{fs} 不得携带 cancel_reason：不得与普通取消混同")
                state.fulfillment_state = fs
                state.checkin_at = p["reported_at"]
                state.actual = {k: p[k] for k in (
                    "actual_room_type", "actual_star_class",
                    "actual_facilities", "note") if k in p}

            elif kind == c.KIND_MERCHANT_ACTION:
                state.merchant_ops.append({"action": p["action"], "acted_at": p["acted_at"],
                                          "note": p.get("note"), "at": at})

            elif kind == c.KIND_PLATFORM_ACTION:
                state.platform_ops.append({"action": p["action"], "acted_at": p["acted_at"],
                                           "actor": p["actor"], "note": p.get("note"), "at": at})
        except DomainError:
            if raise_on_error:
                raise
    return state
