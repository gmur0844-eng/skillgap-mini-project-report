"""The Appearance panel's stored choice: design version, mode and the finalised design (no effect on analyses)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ui_preferences as up  # noqa: E402


class Preferences(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ui_preferences.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_when_nothing_is_stored(self):
        self.assertEqual(up.read(self.path), up.DEFAULT)

    def test_choose_then_finalise_then_reopen(self):
        rec, err = up.update({"version": "v2", "theme": "light"}, self.path)
        self.assertIsNone(err)
        self.assertEqual((rec["version"], rec["theme"], rec["finalised"]), ("v2", "light", None))
        rec, _ = up.update({"finalise": True}, self.path)
        self.assertEqual(rec["finalised"], "v2")
        self.assertTrue(rec["finalised_at"])
        self.assertEqual(up.read(self.path)["finalised"], "v2")       # persisted
        rec, _ = up.update({"theme": "dark"}, self.path)                # the mode changes freely after finalising
        self.assertEqual((rec["theme"], rec["finalised"]), ("dark", "v2"))
        rec, _ = up.update({"clear_final": True, "version": "v1"}, self.path)
        self.assertEqual((rec["version"], rec["finalised"], rec["finalised_at"]), ("v1", None, None))

    def test_invalid_values_are_refused_and_nothing_is_written(self):
        self.assertEqual(up.update({"version": "v3"}, self.path)[0], None)
        self.assertIn("theme", up.update({"theme": "blue"}, self.path)[1])
        self.assertIn("choose a version", up.update({"finalise": True}, self.path)[1])
        self.assertFalse(self.path.exists())


class Route(unittest.TestCase):
    def test_round_trip_through_the_api(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from app.api.v1 import evidence_api
            from app.core.errors import install
        except ImportError as exc:
            raise unittest.SkipTest(f"FastAPI not available: {exc}") from exc
        tmp = tempfile.TemporaryDirectory()
        saved = up.PATH
        up.PATH = Path(tmp.name) / "p.json"
        try:
            app = FastAPI()
            install(app)
            app.include_router(evidence_api.settings_router)
            c = TestClient(app)
            self.assertIsNone(c.get("/api/v1/settings/appearance").json()["version"])
            r = c.post("/api/v1/settings/appearance", json={"version": "v1", "theme": "dark", "finalise": True})
            self.assertEqual((r.status_code, r.json()["finalised"]), (200, "v1"))
            self.assertEqual(c.post("/api/v1/settings/appearance", json={"theme": "x"}).status_code, 422)
        finally:
            up.PATH = saved
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
