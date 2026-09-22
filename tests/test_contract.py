import json
import unittest
from pathlib import Path

from src.contract import validate, validate_event
from src.errors import ValidationError


class ContractTest(unittest.TestCase):
    def test_sample_envelope(self):
        data = json.loads(
            (Path(__file__).parents[1] / "fixtures" / "event.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate(data), [])

    def test_full_payload_valid(self):
        record = {
            "event_id": "e1", "kind": "PRICE_CHANGED",
            "occurred_at": "2026-09-30T20:10:00+08:00",
            "subject_id": "O-1", "version": 1,
            "payload": {
                "quote_ref": "Q-1", "new_price_amount": 1180.0,
                "change_type": "MANUAL", "actor": "MERCHANT",
            },
        }
        self.assertEqual(validate_event(record), [])

    def test_unknown_kind_and_missing_field(self):
        record = {
            "event_id": "e2", "kind": "NOPE",
            "occurred_at": "2026-10-01T15:00:00+08:00",
            "subject_id": "O-1", "version": 1, "payload": {},
        }
        errors = validate_event(record)
        self.assertTrue(any("未知事件 kind" in m for m in errors))

    def test_enum_mismatch_rejected(self):
        record = {
            "event_id": "e3", "kind": "PRICE_CHANGED",
            "occurred_at": "2026-10-01T15:00:00+08:00",
            "subject_id": "O-1", "version": 1,
            "payload": {
                "quote_ref": "Q-1", "new_price_amount": 1,
                "change_type": "MANUAL", "actor": "HACKER",
            },
        }
        errors = validate_event(record)
        self.assertTrue(any("actor 取值非法" in m for m in errors))

    def test_bad_timestamp_and_version(self):
        record = {
            "event_id": "e4", "kind": "QUOTE_FROZEN",
            "occurred_at": "国庆节当天", "subject_id": "O-1", "version": 0,
            "payload": {"quote_ref": "Q-1"},
        }
        errors = validate_event(record)
        self.assertEqual(len(errors), 2)

    def test_require_valid_raises(self):
        with self.assertRaises(ValidationError):
            validate_event  # 仅确认符号可导入
            from src.contract import require_valid
            require_valid({"event_id": "x"})


if __name__ == "__main__":
    unittest.main()
