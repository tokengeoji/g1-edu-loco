import tempfile
import unittest
from pathlib import Path

from .session import create_part, read_json, run_path


class CompletedRunTest(unittest.TestCase):
    def test_cannot_escape_runs_directory(self):
        with self.assertRaises(ValueError):
            run_path("runs", "../../outside")

    def test_failed_write_is_hidden_and_completed_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError):
                with create_part(root, "example", "state", {}) as staging:
                    (staging / "samples.jsonl").write_text("partial", encoding="utf-8")
                    raise RuntimeError("interrupted")
            final = root / "example" / "state"
            self.assertFalse(final.exists())

            metadata = {"source": "synthetic"}
            with create_part(root, "example", "state", metadata) as staging:
                (staging / "samples.jsonl").write_text("{}\n", encoding="utf-8")
                metadata["sample_count"] = 1
            self.assertTrue(read_json(final / "manifest.json")["complete"])
            with self.assertRaises(FileExistsError):
                with create_part(root, "example", "state", {}):
                    self.fail("overwriting an existing run component")
            self.assertEqual((final / "samples.jsonl").read_text(encoding="utf-8"), "{}\n")
