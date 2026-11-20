"""核对随档资料可以读取，以及原始记录引用完整。"""

from pathlib import Path
import tempfile
import unittest

from inspect_records import load_records


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.data = load_records(Path(__file__).resolve().parents[1] / "data" / "records.json")

    def test_record_references(self):
        for source, field, target in [('amendment', 'session', 'sessions'), ('access', 'session', 'sessions'), ('bookings', 'evidence', 'sessions')]:
            group, _, key = target.partition(".")
            keys = {row[key or "id"] for row in self.data[group]}
            for row in self.data[source]:
                refs = row.get(field)
                if refs is None:
                    continue
                refs = refs if isinstance(refs, list) else [refs]
                with self.subTest(kind=source, record=row["id"], field=field):
                    self.assertLessEqual(set(refs), keys)

    def test_duplicate_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"组":[{"id":"1"},{"id":"1"}]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "编号重复"):
                load_records(path)

    def test_source_packet(self):
        sessions = {r["id"]: r for r in self.data["sessions"]}
        for update in self.data["amendment"]:
            who = sessions[update["session"]]
            turn_index = update["turn"] - update["ordinal_origin"]
            self.assertIn(turn_index, range(len(who["turns"])))
        self.assertEqual(sessions["S1"]["joint"], sessions["S2"]["joint"])
        self.assertNotEqual(sessions["S3"]["child"], sessions["S7"]["child"])
        self.assertTrue(any(t.get("audio_missing") for r in sessions.values() for t in r["turns"]))


if __name__ == "__main__":
    unittest.main()
