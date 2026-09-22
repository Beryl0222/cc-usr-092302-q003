import unittest

from src import catalog as c
from src.errors import DomainError
from src.orders import build_order


def ev(event_id, kind, at, payload, subject="O-1", version=1):
    return {
        "event_id": event_id, "kind": kind, "occurred_at": at,
        "subject_id": subject, "version": version, "payload": payload,
    }


def quote(eid="q1", at="2026-09-22T09:00:00+08:00", ref="Q-1", price=880.0,
          channel="PLATFORM"):
    return ev(eid, c.KIND_QUOTE_CAPTURED, at, {
        "channel": channel, "quote_ref": ref, "room_type": "豪华海景大床房",
        "price_amount": price, "currency": "CNY", "captured_at": at,
        "facilities": ["无边泳池", "双早", "正海景"],
    })


def freeze(at="2026-09-22T09:30:00+08:00", ref="Q-1"):
    return ev("f1", c.KIND_QUOTE_FROZEN, at, {"quote_ref": ref})


def price_change(eid, at, new, change_type, actor, old=None):
    p = {"quote_ref": "Q-1", "new_price_amount": new,
         "change_type": change_type, "actor": actor}
    if old is not None:
        p["old_price_amount"] = old
    return ev(eid, c.KIND_PRICE_CHANGED, at, p)


def checkin(eid, state, at="2026-10-01T15:00:00+08:00", **extra):
    p = {"reported_at": at, "fulfillment_state": state, **extra}
    return ev(eid, c.KIND_CHECKIN_REPORTED, at, p)


class PriceInvariantTest(unittest.TestCase):
    def test_frozen_quote_price_never_rewritten(self):
        events = [
            quote(), freeze(),
            price_change("pc1", "2026-09-30T20:10:00+08:00", 1180.0,
                         c.PRICE_CHANGE_MANUAL, c.ACTOR_MERCHANT, old=880.0),
        ]
        state = build_order("O-1", events)
        self.assertEqual(state.frozen_price(), 880.0)       # 原报价不动
        self.assertEqual(state.current_price(), 1180.0)
        self.assertEqual(state.price_delta(), 300.0)

    def test_cannot_freeze_twice(self):
        events = [quote(), freeze(),
                  ev("f2", c.KIND_QUOTE_FROZEN, "2026-09-23T09:00:00+08:00",
                     {"quote_ref": "Q-1"})]
        with self.assertRaises(DomainError):
            build_order("O-1", events)

    def test_price_change_before_freeze_rejected(self):
        with self.assertRaises(DomainError):
            build_order("O-1", [quote(), price_change(
                "pc1", "2026-09-23T09:00:00+08:00", 900,
                c.PRICE_CHANGE_MANUAL, c.ACTOR_MERCHANT)])

    def test_price_change_against_other_quote_rejected(self):
        events = [
            quote(ref="Q-1"), quote(eid="q2", ref="Q-OTA", channel="OTA_A",
                                    at="2026-09-22T09:05:00+08:00", price=850.0),
            freeze(),
            ev("pc1", c.KIND_PRICE_CHANGED, "2026-09-30T20:00:00+08:00", {
                "quote_ref": "Q-OTA", "new_price_amount": 900.0,
                "change_type": c.PRICE_CHANGE_MANUAL, "actor": c.ACTOR_MERCHANT}),
        ]
        with self.assertRaises(DomainError):
            build_order("O-1", events)

    def test_auto_match_vs_manual_liability(self):
        base = [quote(), freeze()]
        auto = base + [price_change("a1", "2026-09-25T10:00:00+08:00", 860.0,
                                    c.PRICE_CHANGE_AUTO_MATCH, c.ACTOR_PLATFORM_AUTO)]
        self.assertEqual(build_order("O-1", auto).liable_party(), c.ACTOR_PLATFORM_AUTO)

        manual = auto + [price_change("m1", "2026-09-30T20:10:00+08:00", 1180.0,
                                      c.PRICE_CHANGE_MANUAL, c.ACTOR_MERCHANT)]
        self.assertEqual(build_order("O-1", manual).liable_party(), c.ACTOR_MERCHANT)

    def test_actor_change_type_must_align(self):
        # 声称自动跟价却由商家发起 → 拒绝
        with self.assertRaises(DomainError):
            build_order("O-1", [quote(), freeze(), price_change(
                "x1", "2026-09-30T20:00:00+08:00", 900.0,
                c.PRICE_CHANGE_AUTO_MATCH, c.ACTOR_MERCHANT)])
        # 手工调价却挂平台自动 → 拒绝
        with self.assertRaises(DomainError):
            build_order("O-1", [quote(), freeze(), price_change(
                "x2", "2026-09-30T20:00:00+08:00", 900.0,
                c.PRICE_CHANGE_MANUAL, c.ACTOR_PLATFORM_AUTO)])

    def test_multi_channel_quotes_coexist(self):
        state = build_order("O-1", [
            quote(ref="Q-1", price=880.0),
            quote(eid="q2", ref="Q-OTA", channel="OTA_A", price=850.0,
                  at="2026-09-22T09:05:00+08:00"),
            freeze(),
        ])
        self.assertEqual(set(state.quotes), {"Q-1", "Q-OTA"})
        self.assertEqual(state.frozen_price(), 880.0)


class FulfillmentStateTest(unittest.TestCase):
    def setUp(self):
        self.base = [quote(), freeze()]

    def test_downgrade_state_is_distinct_and_locked(self):
        events = self.base + [
            ev("p1", c.KIND_ROOM_PROMISED, "2026-09-22T09:31:00+08:00",
               {"room_type": "豪华海景大床房", "star_class": 5,
                "facilities": ["无边泳池", "双早", "正海景", "免费接机"]}),
            checkin("ck1", c.FULFILLMENT_DOWNGRADED,
                    actual_room_type="园景标准间", actual_star_class=3,
                    actual_facilities=["双早"]),
        ]
        state = build_order("O-1", events)
        self.assertEqual(state.fulfillment_state, c.FULFILLMENT_DOWNGRADED)
        gaps = state.downgrade_gaps()
        fields = {g["field"] for g in gaps}
        self.assertEqual(fields, {"room_type", "star_class", "facilities"})

    def test_refusal_and_cancellation_are_distinct(self):
        refused = build_order("O-r", [e for e in self.base] + [
            ev("r1", c.KIND_CHECKIN_REPORTED, "2026-10-01T15:00:00+08:00",
               {"reported_at": "2026-10-01T15:00:00+08:00",
                "fulfillment_state": c.FULFILLMENT_REFUSED_AT_CHECKIN}),
        ])
        cancelled = build_order("O-c", self.base + [
            ev("c1", c.KIND_CHECKIN_REPORTED, "2026-09-29T10:00:00+08:00",
               {"reported_at": "2026-09-29T10:00:00+08:00",
                "fulfillment_state": c.FULFILLMENT_CANCELLED,
                "cancel_reason": c.CANCEL_CONSUMER}, subject="O-c"),
        ])
        self.assertEqual(refused.fulfillment_state, c.FULFILLMENT_REFUSED_AT_CHECKIN)
        self.assertEqual(cancelled.fulfillment_state, c.FULFILLMENT_CANCELLED)

    def test_state_cannot_be_recorded_twice(self):
        with self.assertRaises(DomainError):
            build_order("O-1", self.base + [
                checkin("ck1", c.FULFILLMENT_DOWNGRADED, actual_star_class=3,
                        actual_room_type="标准间", actual_facilities=[]),
                checkin("ck2", c.FULFILLMENT_REFUSED_AT_CHECKIN,
                        at="2026-10-01T16:00:00+08:00"),
            ])

    def test_cancel_requires_reason_but_downgrade_forbids_it(self):
        with self.assertRaises(DomainError):
            build_order("O-1", self.base + [
                checkin("c1", c.FULFILLMENT_CANCELLED),
            ])
        with self.assertRaises(DomainError):
            build_order("O-2", self.base + [
                ev("d1", c.KIND_CHECKIN_REPORTED, "2026-10-01T15:00:00+08:00",
                   {"reported_at": "2026-10-01T15:00:00+08:00",
                    "fulfillment_state": c.FULFILLMENT_DOWNGRADED,
                    "cancel_reason": c.CANCEL_MERCHANT}, subject="O-2"),
            ])


class VersionAppendTest(unittest.TestCase):
    def test_contract_versions_append_only(self):
        events = [
            quote(), freeze(),
            ev("ct1", c.KIND_CONTRACT_VERSION, "2026-09-22T09:40:00+08:00",
               {"contract_ref": "CT", "doc_version": 1, "terms": {"a": 1}}),
            ev("ct2", c.KIND_CONTRACT_VERSION, "2026-09-30T18:00:00+08:00",
               {"contract_ref": "CT", "doc_version": 2, "supersedes_doc_version": 1,
                "terms": {"a": 2}}),
        ]
        state = build_order("O-1", events)
        self.assertEqual([v["doc_version"] for v in state.contract_versions], [1, 2])

    def test_duplicate_contract_version_rejected(self):
        with self.assertRaises(DomainError):
            build_order("O-1", [
                quote(), freeze(),
                ev("ct1", c.KIND_CONTRACT_VERSION, "2026-09-22T09:40:00+08:00",
                   {"contract_ref": "CT", "doc_version": 1, "terms": {}}),
                ev("ct1b", c.KIND_CONTRACT_VERSION, "2026-09-30T18:00:00+08:00",
                   {"contract_ref": "CT", "doc_version": 1, "terms": {}}),
            ])


if __name__ == "__main__":
    unittest.main()
