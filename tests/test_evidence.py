import unittest

from src.domain import DomainError
from src.evidence import EvidenceVault
from tests.helpers import load_scenario, make_event


def _register(material_id: str, hash_: str, submitted: bool = False,
              sensitivity: str = "PROTECTED", version: int = 1) -> dict:
    return make_event(
        f"reg-{material_id}", "EVIDENCE_REGISTERED", material_id,
        "2026-09-20T10:00:00+08:00", version,
        {"material_type": "SCREENSHOT", "title": "截图", "sensitivity": sensitivity,
         "origin": {"method": "SCREENSHOT", "captured_at": "2026-09-20T10:00:00+08:00",
                    "account": "consumer-account"},
         "hash": hash_, "submitted": submitted},
    )


class EvidenceOriginTest(unittest.TestCase):
    def test_verify_origin_by_hash(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "abc123"))
        self.assertTrue(vault.verify_origin("M-1", "", version=None) is False)
        # 用真实哈希校验内容
        from src.domain import sha256_text
        digest = sha256_text("原始截图内容")
        vault2 = EvidenceVault()
        vault2.apply(_register("M-2", digest))
        self.assertTrue(vault2.verify_origin("M-2", "原始截图内容"))
        self.assertFalse(vault2.verify_origin("M-2", "篡改后的内容"))

    def test_verify_historical_version(self):
        from src.domain import sha256_text
        vault = EvidenceVault()
        vault.apply(_register("M-1", sha256_text("v1内容")))
        vault.apply(make_event("v-2", "EVIDENCE_VERSION_ADDED", "M-1",
                               "2026-09-21T10:00:00+08:00", 2, {"hash": sha256_text("v2内容")}))
        self.assertTrue(vault.verify_origin("M-1", "v1内容", version=1))
        self.assertTrue(vault.verify_origin("M-1", "v2内容", version=2))
        self.assertFalse(vault.verify_origin("M-1", "v1内容", version=2))


class EvidenceVersionTest(unittest.TestCase):
    def test_versions_append_only(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1"))
        vault.apply(make_event("v-2", "EVIDENCE_VERSION_ADDED", "M-1",
                               "2026-09-21T10:00:00+08:00", 2, {"hash": "h2"}))
        material = vault.get("M-1")
        self.assertEqual([v.version for v in material.versions], [1, 2])
        self.assertEqual(material.versions[0].hash, "h1")  # 旧版本保留

    def test_duplicate_registration_rejected(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1"))
        with self.assertRaisesRegex(DomainError, "重复注册"):
            vault.apply(_register("M-1", "h1"))


class EvidenceWithdrawTest(unittest.TestCase):
    def test_withdraw_unsubmitted_material(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1", submitted=False))
        vault.apply(make_event("w-1", "EVIDENCE_WITHDRAWN", "M-1",
                               "2026-09-22T10:00:00+08:00", 2))
        self.assertEqual(vault.get("M-1").state, "WITHDRAWN")
        # 撤回后停止公开
        self.assertEqual(vault.public_metadata(), [])

    def test_withdrawn_material_rejects_new_versions(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1"))
        vault.apply(make_event("w-1", "EVIDENCE_WITHDRAWN", "M-1",
                               "2026-09-22T10:00:00+08:00", 2))
        with self.assertRaisesRegex(DomainError, "不能再追加版本"):
            vault.apply(make_event("v-2", "EVIDENCE_VERSION_ADDED", "M-1",
                                   "2026-09-23T10:00:00+08:00", 3, {"hash": "h2"}))

    def test_docketed_material_cannot_be_withdrawn(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1", submitted=True))
        vault.apply(make_event("d-1", "EVIDENCE_DOCKETED", "M-1",
                               "2026-10-02T09:05:00+08:00", 2, {"docket_id": "CASE-1"}))
        with self.assertRaisesRegex(DomainError, "依法留存"):
            vault.apply(make_event("w-1", "EVIDENCE_WITHDRAWN", "M-1",
                                   "2026-10-03T10:00:00+08:00", 3))
        self.assertTrue(vault.get("M-1").retained)

    def test_docketed_material_remains_public_record(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1", submitted=True, sensitivity="PUBLIC"))
        vault.apply(make_event("d-1", "EVIDENCE_DOCKETED", "M-1",
                               "2026-10-02T09:05:00+08:00", 2, {"docket_id": "CASE-1"}))
        self.assertEqual(len(vault.public_metadata()), 1)


class EvidenceSensitivityTest(unittest.TestCase):
    def test_public_metadata_hides_origin_details_for_protected(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1", submitted=True, sensitivity="PROTECTED"))
        entry = vault.public_metadata()[0]
        self.assertNotIn("origin", entry)
        self.assertNotIn("account", str(entry))

    def test_public_material_exposes_origin_method(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1", submitted=True, sensitivity="PUBLIC"))
        entry = vault.public_metadata()[0]
        self.assertEqual(entry["origin_method"], "SCREENSHOT")

    def test_handler_view_keeps_withdrawn_and_origin(self):
        vault = EvidenceVault()
        vault.apply(_register("M-1", "h1"))
        vault.apply(make_event("w-1", "EVIDENCE_WITHDRAWN", "M-1",
                               "2026-09-22T10:00:00+08:00", 2))
        entries = vault.handler_metadata()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["state"], "WITHDRAWN")
        self.assertEqual(entries[0]["origin"]["account"], "consumer-account")


class ScenarioEvidenceTest(unittest.TestCase):
    def test_scenario_materials(self):
        vault = EvidenceVault()
        for event in load_scenario():
            if event["kind"].startswith("EVIDENCE_"):
                vault.apply(event)
        # 报价截图已入卷，依法留存
        self.assertTrue(vault.get("MAT-SCREENSHOT-001").retained)
        # 现场照片追加到 v2 并提交
        photo = vault.get("MAT-PHOTO-001")
        self.assertEqual(photo.latest.version, 2)
        self.assertEqual(photo.state, "SUBMITTED")
        # 聊天记录未提交即撤回，停止公开
        self.assertEqual(vault.get("MAT-CHAT-001").state, "WITHDRAWN")
        public_ids = [m["material_id"] for m in vault.public_metadata()]
        self.assertNotIn("MAT-CHAT-001", public_ids)
        self.assertIn("MAT-SCREENSHOT-001", public_ids)
        # 来源校验：登记哈希可核验原始内容
        self.assertTrue(vault.verify_origin("MAT-SCREENSHOT-001", "OTA报价截图-2026-09-20"))
        self.assertTrue(vault.verify_origin("MAT-PHOTO-001", "现场照片-房间-v2"))
        self.assertTrue(vault.verify_origin("MAT-PHOTO-001", "现场照片-走廊-v1", version=1))


if __name__ == "__main__":
    unittest.main()
