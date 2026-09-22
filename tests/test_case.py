import unittest

from src.case import CaseRegistry
from src.domain import DomainError
from tests.helpers import load_scenario


def _registry() -> CaseRegistry:
    registry = CaseRegistry()
    for event in load_scenario():
        registry.apply(event)
    return registry


class CaseChainTest(unittest.TestCase):
    def test_chain_reconstructs_promise_payment_fulfillment_disposition(self):
        chain = _registry().chain("CASE-2026-0001")
        self.assertEqual(chain["order_id"], "ORD-2026-1001")
        # 承诺：冻结报价 + 套餐承诺 + 调价记录
        self.assertEqual(chain["promise"]["frozen_quote"].price, 1288.0)
        self.assertEqual(chain["promise"]["plan"]["star_level"], 5)
        self.assertEqual(len(chain["promise"]["price_changes"]), 2)
        # 付款
        self.assertEqual(chain["payment"]["total_paid"], 1288.0)
        # 履约：降标异常与商家操作
        self.assertEqual(chain["fulfillment"]["incident"], "ROOM_DOWNGRADE")
        self.assertEqual(chain["fulfillment"]["party_actions"][0]["party"], "MERCHANT")
        # 处置：申诉 + 调解 + 监管移交
        self.assertEqual(chain["disposition"]["appeals"][0]["appeal_id"], "APL-0001")
        self.assertIn("退还差价", chain["disposition"]["mediation"]["outcome"])
        self.assertEqual(chain["disposition"]["referral"]["docket_id"], "REG-2026-888")
        # 承办人可见全部材料（含已撤回）
        material_ids = [m["material_id"] for m in chain["materials"]]
        self.assertIn("MAT-CHAT-001", material_ids)

    def test_case_status_follows_disposition(self):
        registry = _registry()
        self.assertEqual(registry.chain("CASE-2026-0001")["status"], "REFERRED")

    def test_unknown_case_raises(self):
        with self.assertRaisesRegex(DomainError, "不存在"):
            _registry().chain("CASE-NOPE")

    def test_duplicate_complaint_rejected(self):
        registry = _registry()
        complaint = [e for e in load_scenario() if e["kind"] == "COMPLAINT_FILED"][0]
        with self.assertRaisesRegex(DomainError, "已存在"):
            registry.apply(complaint)


class PublicViewTest(unittest.TestCase):
    def setUp(self):
        self.view = _registry().public_view("CASE-2026-0001")

    def test_minimal_personal_information(self):
        # 消费者只显示脱敏化名
        self.assertEqual(self.view["consumer"], "王*")
        # 案件编号打码
        self.assertNotEqual(self.view["case_id"], "CASE-2026-0001")
        self.assertIn("****", self.view["case_id"])
        # 不泄露订单号、支付流水、合同细节
        rendered = str(self.view)
        self.assertNotIn("ORD-2026-1001", rendered)
        self.assertNotIn("PAY-0001", rendered)
        self.assertNotIn("clauses_digest", rendered)

    def test_public_view_keeps_rights_relevant_facts(self):
        self.assertEqual(self.view["promise"]["star_level"], 5)
        self.assertEqual(self.view["promise"]["frozen_price"], 1288.0)
        self.assertEqual(self.view["fulfillment"]["incident"], "ROOM_DOWNGRADE")
        self.assertEqual(self.view["fulfillment"]["actual_star_level"], 3)
        self.assertIn("退还差价", self.view["disposition"]["mediation_outcome"])
        self.assertTrue(self.view["disposition"]["referred"])

    def test_public_view_filters_materials(self):
        material_ids = [m["material_id"] for m in self.view["materials"]]
        # 撤回材料不公开
        self.assertNotIn("MAT-CHAT-001", material_ids)
        # CONFIDENTIAL 材料不公开
        self.assertNotIn("MAT-CONTRACT-001", material_ids)
        # 入卷材料与公开照片可见
        self.assertIn("MAT-SCREENSHOT-001", material_ids)
        self.assertIn("MAT-PHOTO-001", material_ids)


if __name__ == "__main__":
    unittest.main()
