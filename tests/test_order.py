import unittest

from src.domain import DomainError
from src.order import project_order
from tests.helpers import load_scenario, make_event

TS = "2026-09-21T09:00:00+08:00"


def _base_events() -> list[dict]:
    """最小生效订单：报价 → 生效 → 付款。"""
    return [
        make_event("b-1", "QUOTE_SNAPSHOTTED", "ORD-X", "2026-09-20T10:00:00+08:00", 1,
                   {"channel": "OTA", "room_type": "海景房", "price": 1000.0, "currency": "CNY",
                    "captured_at": "2026-09-20T10:00:00+08:00"}),
        make_event("b-2", "PLAN_FROZEN", "ORD-X", TS, 2,
                   {"channel": "OTA", "room_type": "海景房", "star_level": 5,
                    "facilities": ["早餐"], "package_items": ["两晚"],
                    "total_price": 1000.0, "currency": "CNY"}),
        make_event("b-3", "PAYMENT_RECORDED", "ORD-X", "2026-09-21T09:05:00+08:00", 3,
                   {"payment_id": "P-1", "amount": 1000.0, "currency": "CNY", "method": "ALIPAY"}),
    ]


class OrderFreezeTest(unittest.TestCase):
    def test_frozen_quote_not_rewritable(self):
        events = _base_events()
        events.append(make_event("b-4", "PLAN_FROZEN", "ORD-X", "2026-09-22T09:00:00+08:00", 4,
                                 {"channel": "OTA", "room_type": "海景房", "star_level": 5,
                                  "facilities": [], "package_items": [],
                                  "total_price": 1500.0, "currency": "CNY"}))
        with self.assertRaisesRegex(DomainError, "不可改写"):
            project_order(events)

    def test_quote_snapshot_not_rewritable(self):
        events = [
            make_event("q-1", "QUOTE_SNAPSHOTTED", "ORD-X", "2026-09-20T10:00:00+08:00", 1,
                       {"channel": "OTA", "room_type": "海景房", "price": 1000.0, "currency": "CNY",
                        "captured_at": "2026-09-20T10:00:00+08:00"}),
            make_event("q-2", "QUOTE_SNAPSHOTTED", "ORD-X", "2026-09-20T11:00:00+08:00", 2,
                       {"channel": "OTA", "room_type": "海景房", "price": 1200.0, "currency": "CNY",
                        "captured_at": "2026-09-20T11:00:00+08:00"}),
        ]
        with self.assertRaisesRegex(DomainError, "拒绝改写"):
            project_order(events)

    def test_price_change_appended_without_touching_frozen_quote(self):
        events = _base_events()
        events.append(make_event("b-4", "PRICE_CHANGED", "ORD-X", "2026-09-28T20:00:00+08:00", 4,
                                 {"channel": "OTA", "room_type": "海景房", "old_price": 1000.0,
                                  "new_price": 1500.0, "actor": "MERCHANT_MANUAL"}))
        state = project_order(events)
        self.assertEqual(state.frozen_quote.price, 1000.0)  # 原报价不被调价改写
        self.assertEqual(len(state.price_changes), 1)

    def test_price_change_requires_frozen_plan(self):
        events = [make_event("p-1", "PRICE_CHANGED", "ORD-X", TS, 1,
                             {"channel": "OTA", "room_type": "海景房", "old_price": 1,
                              "new_price": 2, "actor": "PLATFORM_AUTO"})]
        with self.assertRaisesRegex(DomainError, "未生效"):
            project_order(events)

    def test_price_change_responsibility_attributed(self):
        scenario = load_scenario()
        order_events = [e for e in scenario if e["subject_id"] == "ORD-2026-1001"]
        state = project_order(order_events)
        platform = state.price_changes_by("PLATFORM_AUTO")
        merchant = state.price_changes_by("MERCHANT_MANUAL")
        self.assertEqual(len(platform), 1)
        self.assertEqual(platform[0].new_price, 1188.0)
        self.assertEqual(len(merchant), 1)
        self.assertEqual(merchant[0].new_price, 1588.0)


class OrderIncidentTest(unittest.TestCase):
    def _cancel(self, mode: str, version: int = 4) -> dict:
        return make_event(f"c-{version}", "ORDER_CANCELLED", "ORD-X", "2026-09-30T10:00:00+08:00",
                          version, {"mode": mode})

    def test_plain_cancel_distinct_from_incidents(self):
        state = project_order(_base_events() + [self._cancel("CONSUMER")])
        self.assertEqual(state.lifecycle, "CANCELLED")
        self.assertEqual(state.incident, "CANCELLED")

    def test_downgrade_and_cancel_not_mergeable(self):
        events = _base_events() + [
            make_event("i-1", "ROOM_DOWNGRADED", "ORD-X", "2026-10-01T15:30:00+08:00", 4,
                       {"promised_room_type": "海景房", "actual_room_type": "城景房",
                        "promised_star_level": 5, "actual_star_level": 3}),
            self._cancel("CONSUMER", version=5),
        ]
        with self.assertRaisesRegex(DomainError, "不得混为同一状态"):
            project_order(events)

    def test_refusal_then_force_cancel_is_refusal_lineage(self):
        events = _base_events() + [
            make_event("r-1", "STAY_REFUSED", "ORD-X", "2026-10-01T14:00:00+08:00", 4,
                       {"reason": "商家声称满房"}),
            self._cancel("MERCHANT", version=5),
        ]
        state = project_order(events)
        self.assertEqual(state.incident, "FORCE_CANCELLED")
        self.assertEqual(state.lifecycle, "CANCELLED")
        self.assertIn("满房", state.incident_detail["reason"])

    def test_double_cancel_rejected(self):
        events = _base_events() + [self._cancel("CONSUMER"), self._cancel("MERCHANT", version=5)]
        with self.assertRaises(DomainError):
            project_order(events)

    def test_no_events_after_cancel_except_allowed(self):
        events = _base_events() + [
            self._cancel("CONSUMER"),
            make_event("x-1", "CHECKIN_RECORDED", "ORD-X", "2026-10-01T15:00:00+08:00", 5,
                       {"actual_room_type": "城景房", "actual_star_level": 3, "facilities_observed": []}),
        ]
        with self.assertRaisesRegex(DomainError, "已取消"):
            project_order(events)


class OrderPaymentTest(unittest.TestCase):
    def test_duplicate_payment_rejected(self):
        events = _base_events()
        events.append(make_event("p-2", "PAYMENT_RECORDED", "ORD-X", "2026-09-21T10:00:00+08:00", 4,
                                 {"payment_id": "P-1", "amount": 1000.0, "currency": "CNY",
                                  "method": "ALIPAY"}))
        with self.assertRaisesRegex(DomainError, "重复"):
            project_order(events)

    def test_price_difference_against_frozen_quote(self):
        events = _base_events()
        events.append(make_event("p-2", "PAYMENT_RECORDED", "ORD-X", "2026-09-22T10:00:00+08:00", 4,
                                 {"payment_id": "P-2", "amount": 300.0, "currency": "CNY",
                                  "method": "WECHAT"}))
        state = project_order(events)
        self.assertEqual(state.total_paid, 1300.0)
        self.assertEqual(state.price_difference, 300.0)

    def test_contract_versions_append_only(self):
        events = _base_events() + [
            make_event("ct-1", "CONTRACT_PUBLISHED", "ORD-X", "2026-09-21T09:01:00+08:00", 4,
                       {"contract_version": 1, "clauses_digest": "d1"}),
            make_event("ct-2", "CONTRACT_PUBLISHED", "ORD-X", "2026-09-22T09:01:00+08:00", 5,
                       {"contract_version": 1, "clauses_digest": "d1-modified"}),
        ]
        with self.assertRaisesRegex(DomainError, "只能追加新版本"):
            project_order(events)


class ScenarioOrderTest(unittest.TestCase):
    def test_scenario_order_projection(self):
        order_events = [e for e in load_scenario() if e["subject_id"] == "ORD-2026-1001"]
        state = project_order(order_events)
        self.assertEqual(state.frozen_quote.price, 1288.0)
        self.assertEqual(state.plan["star_level"], 5)
        self.assertEqual(state.total_paid, 1288.0)
        self.assertEqual(state.incident, "ROOM_DOWNGRADE")
        self.assertEqual(state.incident_detail["actual_star_level"], 3)
        self.assertEqual(len(state.appeals), 1)
        self.assertEqual(state.appeals[0]["claimed_difference"], 300.0)


if __name__ == "__main__":
    unittest.main()
