import hashlib
import unittest

from src import catalog as c
from src.errors import DomainError
from src.evidence import build_registry, verify_raw_hash, effective_sensitivity


def h(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def ev(event_id, kind, at, payload, subject="O-1", version=1):
    return {"event_id": event_id, "kind": kind, "occurred_at": at,
            "subject_id": subject, "version": version, "payload": payload}


def upload(eid="EV-1", state=c.EV_DRAFT, sensitivity=c.SENSITIVITY_PUBLIC,
           etype=c.EV_SCREENSHOT, tags=None, source="consumer_app_capture"):
    return ev(f"up-{eid}", c.KIND_EVIDENCE_UPLOADED, "2026-10-01T10:00:00+08:00", {
        "evidence_id": eid, "evidence_type": etype, "source": source,
        "raw_hash": h(b"v1"), "filename": "f.png",
        "sensitivity": sensitivity, "state": state, **({"field_tags": tags} if tags else {}),
    })


class ProvenanceTest(unittest.TestCase):
    def test_hash_roundtrip(self):
        data = b"original bytes"
        self.assertTrue(verify_raw_hash(data, h(data)))
        self.assertFalse(verify_raw_hash(b"tampered", h(data)))

    def test_bad_hash_protocol_rejected(self):
        bad = ev("x", c.KIND_EVIDENCE_UPLOADED, "2026-10-01T10:00:00+08:00", {
            "evidence_id": "EV-X", "evidence_type": c.EV_SCREENSHOT,
            "source": "app", "raw_hash": "md5:abc",
            "sensitivity": c.SENSITIVITY_PUBLIC})
        with self.assertRaises(DomainError):
            build_registry([bad])

    def test_field_tags_escalate_sensitivity(self):
        level = effective_sensitivity(c.SENSITIVITY_PUBLIC,
                                      {"phone": c.SENSITIVITY_RESTRICTED})
        self.assertEqual(level, c.SENSITIVITY_RESTRICTED)


class LifecycleTest(unittest.TestCase):
    def test_draft_can_be_withdrawn_and_disappears_from_public(self):
        reg = build_registry([
            upload("EV-D", state=c.EV_DRAFT),
            ev("w", c.KIND_EVIDENCE_WITHDRAWN, "2026-10-01T11:00:00+08:00",
               {"evidence_ref": "EV-D", "reason": "录错了"}),
        ])
        item = reg["EV-D"]
        self.assertEqual(item.state, c.EV_WITHDRAWN)
        self.assertFalse(item.is_publicly_visible())

    def test_submitted_material_cannot_be_withdrawn_by_consumer(self):
        with self.assertRaises(DomainError):
            build_registry([
                upload("EV-S", state=c.EV_SUBMITTED),
                ev("w", c.KIND_EVIDENCE_WITHDRAWN, "2026-10-01T11:00:00+08:00",
                   {"evidence_ref": "EV-S"}),
            ])

    def test_held_evidence_must_be_retained(self):
        # 即便先尝试撤回（在 SUBMITTED 上本就不允许），进入卷宗后更是绝对留置
        with self.assertRaises(DomainError):
            build_registry([
                upload("EV-H", state=c.EV_SUBMITTED, sensitivity=c.SENSITIVITY_INTERNAL),
                ev("hold", c.KIND_EVIDENCE_HELD, "2026-10-02T09:00:00+08:00", {
                    "evidence_ref": "EV-H", "case_ref": "CASE-1",
                    "held_at": "2026-10-02T09:00:00+08:00",
                    "docket": "12315-1", "authority": "市监局"}),
                ev("w", c.KIND_EVIDENCE_WITHDRAWN, "2026-10-03T09:00:00+08:00",
                   {"evidence_ref": "EV-H"}),
            ])

        reg = build_registry([
            upload("EV-H", state=c.EV_SUBMITTED, sensitivity=c.SENSITIVITY_INTERNAL),
            ev("hold", c.KIND_EVIDENCE_HELD, "2026-10-02T09:00:00+08:00", {
                "evidence_ref": "EV-H", "case_ref": "CASE-1",
                "held_at": "2026-10-02T09:00:00+08:00",
                "docket": "12315-1", "authority": "市监局"}),
        ])
        self.assertEqual(reg["EV-H"].state, c.EV_HELD)
        self.assertIsNotNone(reg["EV-H"].held_by)

    def test_resubmit_is_append_version_only(self):
        reg = build_registry([
            upload("EV-C", state=c.EV_SUBMITTED, etype=c.EV_CONTRACT,
                   sensitivity=c.SENSITIVITY_INTERNAL, source="esign_vault"),
            ev("v2", c.KIND_EVIDENCE_RESUBMITTED, "2026-10-01T12:00:00+08:00", {
                "evidence_ref": "EV-C", "doc_version": 2,
                "source": "esign_vault", "raw_hash": h(b"v2"),
                "filename": "c2.pdf", "sensitivity": c.SENSITIVITY_INTERNAL}),
        ])
        item = reg["EV-C"]
        self.assertEqual([v.doc_version for v in item.versions], [1, 2])
        self.assertEqual(item.raw_hash, h(b"v2"))  # 当前指向新版本
        self.assertEqual(item.versions[0].raw_hash, h(b"v1"))  # 旧版本保留

    def test_resubmit_version_must_be_sequential(self):
        with self.assertRaises(DomainError):
            build_registry([
                upload("EV-C"),
                ev("v3", c.KIND_EVIDENCE_RESUBMITTED, "2026-10-01T12:00:00+08:00", {
                    "evidence_ref": "EV-C", "doc_version": 3,
                    "source": "app", "raw_hash": h(b"v3")}),
            ])

    def test_withdrawn_evidence_cannot_receive_versions(self):
        with self.assertRaises(DomainError):
            build_registry([
                upload("EV-D", state=c.EV_DRAFT),
                ev("w", c.KIND_EVIDENCE_WITHDRAWN, "2026-10-01T10:30:00+08:00",
                   {"evidence_ref": "EV-D"}),
                ev("v2", c.KIND_EVIDENCE_RESUBMITTED, "2026-10-01T11:00:00+08:00", {
                    "evidence_ref": "EV-D", "doc_version": 2,
                    "source": "app", "raw_hash": h(b"v2")}),
            ])


if __name__ == "__main__":
    unittest.main()
