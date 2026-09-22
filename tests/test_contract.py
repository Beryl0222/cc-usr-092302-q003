import json
import unittest
from pathlib import Path

from src.contract import validate, validate_event
from tests.helpers import load_scenario, make_event


class ContractTest(unittest.TestCase):
    def test_sample(self):
        data = json.loads((Path(__file__).parents[1] / "fixtures" / "event.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(data), [])

    def test_envelope_missing_fields(self):
        self.assertEqual(validate({"kind": "PLAN_FROZEN"}), ["event_id", "occurred_at", "subject_id", "version"])

    def test_valid_event_passes_full_validation(self):
        event = make_event(
            "e-1", "QUOTE_SNAPSHOTTED", "ORD-1", "2026-09-20T10:00:00+08:00", 1,
            {"channel": "OTA", "room_type": "海景房", "price": 1288.0, "currency": "CNY",
             "captured_at": "2026-09-20T10:00:00+08:00"},
        )
        self.assertEqual(validate_event(event), [])

    def test_unknown_kind_rejected(self):
        event = make_event("e-2", "PRICE_MAGIC", "ORD-1", "2026-09-20T10:00:00+08:00", 1)
        self.assertTrue(any("未知事件类型" in e for e in validate_event(event)))

    def test_missing_payload_fields_reported(self):
        event = make_event("e-3", "PRICE_CHANGED", "ORD-1", "2026-09-25T08:00:00+08:00", 2,
                           {"channel": "OTA", "room_type": "海景房"})
        errors = validate_event(event)
        self.assertTrue(any("old_price" in e for e in errors))
        self.assertTrue(any("actor" in e for e in errors))

    def test_enum_fields_checked(self):
        event = make_event("e-4", "PRICE_CHANGED", "ORD-1", "2026-09-25T08:00:00+08:00", 2,
                           {"channel": "OTA", "room_type": "海景房", "old_price": 1, "new_price": 2,
                            "actor": "CONSUMER"})
        self.assertTrue(any("payload.actor" in e for e in validate_event(event)))

    def test_timezone_required(self):
        event = make_event("e-5", "STAY_REFUSED", "ORD-1", "2026-10-01T15:00:00", 3, {"reason": "满房"})
        self.assertTrue(any("时区" in e for e in validate_event(event)))

    def test_version_must_be_positive_int(self):
        event = make_event("e-6", "STAY_REFUSED", "ORD-1", "2026-10-01T15:00:00+08:00", 0, {"reason": "满房"})
        self.assertTrue(any("version" in e for e in validate_event(event)))

    def test_scenario_fixture_all_valid(self):
        for event in load_scenario():
            self.assertEqual(validate_event(event), [], f"fixture 事件 {event['event_id']} 校验失败")


if __name__ == "__main__":
    unittest.main()
