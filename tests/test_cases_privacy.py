import json
import unittest
from pathlib import Path

from src import catalog as c
from src.cases import build_case_view
from src.ingest import ingest_batch
from src.privacy import build_public_view, mask_phone, mask_name, mask_id_card
from src.store import EventStore

FIXTURE = Path(__file__).parents[1] / "fixtures" / "case.json"


def load_case():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class EndToEndCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_case()
        # 模拟真实批量导入：所有事件先入一个存储，乱序由导入器重排
        cls.store = EventStore()
        all_events = (cls.data["order_events"]
                      + cls.data["evidence_events"]
                      + cls.data["case_events"])
        # 故意打乱顺序，验证乱序导入
        import random
        rng = random.Random(42)
        shuffled = all_events[:]
        rng.shuffle(shuffled)
        cls.report = ingest_batch(cls.store, shuffled)
        cls.case = build_case_view(
            cls.store.stream(cls.data["case_ref"]),
            cls.store.stream(cls.data["order_subject_id"]),
            cls.store.stream(cls.data["order_subject_id"]),
        )

    def test_batch_ingested_cleanly(self):
        self.assertTrue(self.report.ok, self.report.rejected)
        self.assertEqual(len(self.report.accepted), 28)

    def test_chain_sections_present(self):
        chain = self.case.chain()
        for section in ("commitment", "payment", "fulfillment", "disposition"):
            self.assertIn(section, chain)

    def test_frozen_quote_intact_after_markup(self):
        order = self.case.order
        self.assertEqual(order.frozen_price(), 880.0)
        self.assertEqual(order.current_price(), 1180.0)
        # 冻结快照里的 880 元一个字都没被改
        self.assertEqual(
            order.quotes[order.frozen_quote_ref]["price_amount"], 880.0)

    def test_liability_falls_on_merchant_manual_markup(self):
        # 最后一次变动是商家手工加价（此前平台自动跟价 880→860 责任在平台）
        self.assertEqual(self.case.order.liable_party(), c.ACTOR_MERCHANT)
        changes = self.case.chain()["fulfillment"]["price_changes"]
        self.assertEqual([x["change_type"] for x in changes],
                         ["AUTO_MATCH", "MANUAL"])

    def test_downgrade_is_not_confused_with_cancellation(self):
        self.assertEqual(self.case.order.fulfillment_state,
                         c.FULFILLMENT_DOWNGRADED)
        self.assertNotEqual(self.case.order.fulfillment_state,
                            c.FULFILLMENT_CANCELLED)
        gaps = self.case.order.downgrade_gaps()
        star = next(g for g in gaps if g["field"] == "star_class")
        self.assertEqual((star["promised"], star["actual"]), (5, 3))

    def test_contract_versions_both_retained(self):
        versions = [v["doc_version"] for v in self.case.order.contract_versions]
        self.assertEqual(versions, [1, 2])

    def test_withdrawn_draft_not_public_but_held_chat_retained(self):
        reg = self.case.evidence
        self.assertEqual(reg["EV-AUDIO-DRAFT"].state, c.EV_WITHDRAWN)
        chat = reg["EV-CHAT-01"]
        self.assertEqual(chat.state, c.EV_HELD)
        self.assertEqual(chat.held_by["docket"], "12315-2026-1002-77")

    def test_disposition_chain_appeal_mediation_referral(self):
        d = self.case.chain()["disposition"]
        self.assertEqual(d["appeal"]["appeal_ref"], "APL-77")
        self.assertEqual(d["mediations"][0]["outcome"], "PARTIAL_AWARD")
        self.assertIsNotNone(d["referral"])
        self.assertEqual(d["closure"]["resolution"],
                         "PLATFORM_COMPENSATED_AND_REGULATOR_INVESTIGATING")

    def test_timeline_is_continuous(self):
        ats = [x["at"] for x in self.case.timeline]
        self.assertEqual(ats, sorted(ats))
        stages = {x["stage"] for x in self.case.timeline}
        self.assertEqual(stages, {"order", "evidence", "case"})


class PublicViewTest(unittest.TestCase):
    def test_masking_helpers(self):
        self.assertEqual(mask_name("林小满"), "林**")
        self.assertEqual(mask_phone("138-0000-1234"), "138****1234")
        self.assertTrue(mask_id_card("11010119900101001X").startswith("110"))
        self.assertTrue(mask_id_card("11010119900101001X").endswith("01X"))

    def test_public_view_minimizes_pii(self):
        data = load_case()
        store = EventStore()
        ingest_batch(store, data["order_events"] + data["evidence_events"]
                     + data["case_events"])
        case = build_case_view(store.stream(data["case_ref"]),
                               store.stream(data["order_subject_id"]),
                               store.stream(data["order_subject_id"]))
        pub = build_public_view(case, data["consumer_pii"])

        self.assertEqual(pub.consumer["name"], "林**")
        self.assertEqual(pub.consumer["phone"], "138****1234")
        self.assertNotIn("11010119900101001X", pub.consumer["id_card"])

        self.assertEqual(pub.promised_room_type, "豪华海景大床房")
        self.assertEqual(pub.frozen_price, 880.0)
        self.assertEqual(pub.liable_party, c.ACTOR_MERCHANT)
        self.assertEqual(pub.fulfillment_state, c.FULFILLMENT_DOWNGRADED)
        self.assertTrue(pub.referred_to_authority)

        # 只放行 PUBLIC + SUBMITTED：截图与现场照片可见；
        # 聊天记录（HELD/INTERNAL）、合同（INTERNAL）、撤回录音不公开
        visible = {e["evidence_ref"] for e in pub.public_evidence}
        self.assertEqual(visible, {"EV-SHOT-01", "EV-PHOTO-01"})
        self.assertGreaterEqual(pub.withheld_count, 3)


if __name__ == "__main__":
    unittest.main()
