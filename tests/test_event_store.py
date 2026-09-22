import unittest

from src.domain import ConflictError, DomainError
from src.event_store import EventStore
from tests.helpers import load_scenario, make_event


def _quote_event(event_id: str, occurred_at: str, price: float = 1288.0) -> dict:
    return make_event(
        event_id, "QUOTE_SNAPSHOTTED", "ORD-T", occurred_at, 1,
        {"channel": "OTA", "room_type": "海景房", "price": price, "currency": "CNY",
         "captured_at": occurred_at},
    )


class EventStoreTest(unittest.TestCase):
    def test_duplicate_same_content_is_idempotent(self):
        store = EventStore()
        event = _quote_event("e-1", "2026-09-20T10:00:00+08:00")
        self.assertTrue(store.append(event))
        self.assertFalse(store.append(dict(event)))
        self.assertEqual(len(store), 1)

    def test_same_id_different_content_conflicts(self):
        store = EventStore()
        store.append(_quote_event("e-1", "2026-09-20T10:00:00+08:00", price=1288.0))
        with self.assertRaises(ConflictError):
            store.append(_quote_event("e-1", "2026-09-20T10:00:00+08:00", price=999.0))

    def test_replay_sorted_by_occurred_at_not_insertion(self):
        store = EventStore()
        later = _quote_event("e-2", "2026-09-20T12:00:00+08:00")
        earlier = _quote_event("e-1", "2026-09-20T09:00:00+08:00")
        store.append(later)
        store.append(earlier)
        self.assertEqual([e["event_id"] for e in store.replay()], ["e-1", "e-2"])

    def test_replay_filters_by_subject(self):
        store = EventStore()
        store.append(_quote_event("e-1", "2026-09-20T10:00:00+08:00"))
        store.append(make_event("e-2", "STAY_REFUSED", "ORD-OTHER",
                                "2026-10-01T15:00:00+08:00", 1, {"reason": "满房"}))
        self.assertEqual([e["event_id"] for e in store.replay("ORD-T")], ["e-1"])

    def test_import_batch_reports_duplicates_and_rejects(self):
        store = EventStore()
        good = _quote_event("e-1", "2026-09-20T10:00:00+08:00")
        invalid = make_event("e-2", "PRICE_MAGIC", "ORD-T", "2026-09-20T11:00:00+08:00", 1)
        report = store.import_batch([good, dict(good), invalid])
        self.assertEqual((report.total, report.added, report.duplicates, report.rejected), (3, 1, 1, 1))

    def test_scenario_imports_clean_and_reimport_is_idempotent(self):
        store = EventStore()
        scenario = load_scenario()
        first = store.import_batch(scenario)
        self.assertEqual((first.added, first.duplicates, first.rejected), (len(scenario), 0, 0))
        second = store.import_batch(scenario)
        self.assertEqual((second.added, second.duplicates, second.rejected), (0, len(scenario), 0))

    def test_out_of_order_import_still_replays_in_order(self):
        store = EventStore()
        scenario = load_scenario()
        store.import_batch(list(reversed(scenario)))
        order_events = store.replay("ORD-2026-1001")
        kinds = [e["kind"] for e in order_events]
        self.assertEqual(kinds[0], "QUOTE_SNAPSHOTTED")
        self.assertEqual(kinds[-1], "PARTY_ACTION_RECORDED")
        self.assertLess(order_events[0]["occurred_at"], order_events[-1]["occurred_at"])

    def test_invalid_event_rejected_on_append(self):
        store = EventStore()
        with self.assertRaises(DomainError):
            store.append(make_event("e-9", "STAY_REFUSED", "ORD-T", "not-a-time", 1, {"reason": "x"}))


if __name__ == "__main__":
    unittest.main()
