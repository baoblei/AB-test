import sqlite3
import unittest
from datetime import datetime, timezone

from app_core.database import migrate_business_times
from app_core.time_utils import beijing_today, legacy_utc_to_beijing_iso, now_beijing_iso


class BeijingTimeTests(unittest.TestCase):
    def test_now_beijing_iso_uses_fixed_offset(self):
        value = now_beijing_iso(datetime(2026, 7, 15, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual(value, "2026-07-15T09:02:03+08:00")
        self.assertEqual(
            beijing_today(datetime(2026, 7, 14, 16, 0, 0, tzinfo=timezone.utc)),
            "2026-07-15",
        )

    def test_legacy_utc_conversion_preserves_new_and_invalid_values(self):
        self.assertEqual(
            legacy_utc_to_beijing_iso("2026-07-14 16:30:00"),
            "2026-07-15T00:30:00+08:00",
        )
        self.assertEqual(
            legacy_utc_to_beijing_iso("2026-07-15T00:30:00+08:00"),
            "2026-07-15T00:30:00+08:00",
        )
        self.assertEqual(legacy_utc_to_beijing_iso("invalid"), "invalid")
        self.assertIsNone(legacy_utc_to_beijing_iso(None))

    def test_database_migration_runs_once(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, created_at TEXT, last_login TEXT)")
        conn.execute("CREATE TABLE operation_logs (id INTEGER PRIMARY KEY, timestamp TEXT)")
        conn.execute("CREATE TABLE results_log (id INTEGER PRIMARY KEY, timestamp TEXT)")
        conn.execute("INSERT INTO users VALUES (1, '2026-07-14 16:00:00', NULL)")
        conn.execute("INSERT INTO operation_logs VALUES (1, '2026-07-14 16:10:00')")
        conn.execute("INSERT INTO results_log VALUES (1, '2026-07-14 16:20:00')")
        conn.execute("INSERT INTO results_log VALUES (2, 'invalid')")

        first = migrate_business_times(conn)
        second = migrate_business_times(conn)

        self.assertEqual(first["updated"], 3)
        self.assertEqual(first["invalid"], 1)
        self.assertEqual(second, {"updated": 0, "invalid": 0})
        self.assertEqual(
            conn.execute("SELECT timestamp FROM results_log WHERE id=1").fetchone()[0],
            "2026-07-15T00:20:00+08:00",
        )

