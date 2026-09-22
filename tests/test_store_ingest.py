import unittest

from src.ingest import ingest_batch
from src.store import EventStore
from src.errors import ConflictError


def envelope(event_id, kind, at, subject, payload, version=1):
    return {
        "event_id": event_id, "kind": kind, "occurred_at": at,
        "subject_id": subject, "version": version, "payload": payload,
    }


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = EventStore()

    def test_versions_must_be_sequential(self):
        e = envelope("e1", "MERCHANT_ACTION", "2026-10-01T12:00:00+08:00", "O-1",
                     {"action": "X", "acted_at": "2026-10-01T12:00:00+08:00"})
        self.store.append(e)
        e2 = envelope("e2", "MERCHANT_ACTION", "2026-10-01T13:00:00+08:00", "O-1",
                      {"action": "Y", "acted_at": "2026-10-01T13:00:00+08:00"}, version=3)
        with self.assertRaises(ConflictError):
            self.store.append(e2)

    def test_duplicate_event_id_is_idempotent(self):
        e = envelope("e1", "MERCHANT_ACTION", "2026-10-01T12:00:00+08:00", "O-1",
                     {"action": "X", "acted_at": "2026-10-01T12:00:00+08:00"})
        self.store.append(e)
        self.store.append(dict(e))  # 完全相同的重复投递
        self.assertEqual(len(self.store.stream("O-1")), 1)

    def test_same_id_different_content_rejected(self):
        e = envelope("e1", "MERCHANT_ACTION", "2026-10-01T12:00:00+08:00", "O-1",
                     {"action": "X", "acted_at": "2026-10-01T12:00:00+08:00"})
        tampered = envelope("e1", "MERCHANT_ACTION", "2026-10-01T12:00:00+08:00", "O-1",
                            {"action": "CHANGED", "acted_at": "2026-10-01T12:00:00+08:00"})
        self.store.append(e)
        with self.assertRaises(ConflictError):
            self.store.append(tampered)

    def test_stream_reorders_by_business_time(self):
        late = envelope("late", "MERCHANT_ACTION", "2026-10-02T12:00:00+08:00", "O-1",
                        {"action": "LATE", "acted_at": "2026-10-02T12:00:00+08:00"})
        early = envelope("early", "MERCHANT_ACTION", "2026-10-01T12:00:00+08:00", "O-1",
                         {"action": "EARLY", "acted_at": "2026-10-01T12:00:00+08:00"},
                         version=2)
        self.store.append(late)
        self.store.append(early)
        ordered = self.store.stream("O-1")
        self.assertEqual([e["event_id"] for e in ordered], ["early", "late"])


class IngestTest(unittest.TestCase):
    def test_batch_out_of_order_gets_versions(self):
        store = EventStore()
        mk = lambda eid, at: envelope(eid, "MERCHANT_ACTION", at, "O-9",
                                      {"action": eid, "acted_at": at})
        batch = [
            mk("b-late", "2026-10-03T10:00:00+08:00"),
            mk("b-early", "2026-10-01T10:00:00+08:00"),
            mk("b-mid", "2026-10-02T10:00:00+08:00"),
        ]
        report = ingest_batch(store, batch)
        self.assertTrue(report.ok)
        self.assertEqual(
            [e["payload"]["action"] for e in store.stream("O-9")],
            ["b-early", "b-mid", "b-late"],
        )
        self.assertEqual([e["version"] for e in store.stream("O-9")], [1, 2, 3])

    def test_batch_duplicates_and_invalid(self):
        store = EventStore()
        good = envelope("d1", "MERCHANT_ACTION", "2026-10-01T10:00:00+08:00", "O-9",
                        {"action": "A", "acted_at": "2026-10-01T10:00:00+08:00"})
        report1 = ingest_batch(store, [good])
        self.assertEqual(report1.accepted, ["d1"])
        # 再来：同 event_id 重复 + 一条非法
        bad = {"event_id": "d2", "kind": "MERCHANT_ACTION",
               "occurred_at": "2026-10-01T11:00:00+08:00",
               "subject_id": "O-9", "version": 1, "payload": {}}
        report2 = ingest_batch(store, [dict(good), bad])
        self.assertEqual(report2.duplicates, ["d1"])
        self.assertEqual(len(report2.rejected), 1)
        self.assertEqual(report2.rejected[0]["event_id"], "d2")

    def test_platform_receipt_dedup_by_fingerprint(self):
        store = EventStore()
        rec = lambda eid: envelope(eid, "EVIDENCE_UPLOADED",
                                   "2026-10-01T10:00:00+08:00", "O-9", {
                                       "evidence_id": eid, "evidence_type": "RECEIPT",
                                       "source": "platform_callback",
                                       "raw_hash": "sha256:" + "a" * 64,
                                       "sensitivity": "INTERNAL"})
        r1 = ingest_batch(store, [rec("rcpt-1")])
        r2 = ingest_batch(store, [rec("rcpt-2")])  # 不同 event_id，同一回执指纹
        self.assertEqual(r1.accepted, ["rcpt-1"])
        self.assertEqual(r2.duplicates, ["rcpt-2"])


if __name__ == "__main__":
    unittest.main()
