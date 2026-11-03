"""The registered Qwen replay must stay loadable: any edit of engine_config.semantic_ai (every key except
`providers` is part of the replay cache key) would silently switch the pipeline to the deterministic fallback.
Found in the improvement release, when a new key briefly lived under semantic_ai."""
import unittest
from pathlib import Path

from app.knowledge_engine.config import load_config
from app.knowledge_engine.intelligence_stage import semantic_setup

REPO = Path(__file__).resolve().parents[2]


from tests.data_requirements import requires_replay_recording  # noqa: E402


@requires_replay_recording
class ReplayKeyStability(unittest.TestCase):
    def test_registered_replay_is_selected_with_the_shipped_configuration(self):
        adj, info = semantic_setup(load_config(), REPO)
        if info["mode"] == "LIVE":
            self.skipTest("a live model endpoint is reachable; replay is not selected in that case")
        self.assertEqual(info["mode"], "REPLAY_VERIFIED_RUN", info.get("replay_rejected"))
        self.assertEqual(adj.status, "AI_PROVIDER_REPLAYED")

    def test_replay_key_does_not_depend_on_the_endpoint_address(self):
        # regression (Mac RC, 2026-10-09): OLLAMA_URL=http://127.0.0.1:9, used to keep a release build off the live
        # model, changed the provider description and so the cache key: replay was rejected and the run silently
        # fell back to the deterministic rules (a different run)
        from unittest import mock
        for env in ({"OLLAMA_URL": "http://127.0.0.1:9"}, {"OLLAMA_URL": "http://10.0.0.5:11434"},
                    {"SEMANTIC_MODE": "replay"}):
            with mock.patch.dict("os.environ", env):
                adj, info = semantic_setup(load_config(), REPO)
                if info["mode"] == "LIVE":
                    continue
                self.assertEqual(info["mode"], "REPLAY_VERIFIED_RUN", (env, info.get("replay_rejected")))

    def test_semantic_mode_replay_never_goes_live(self):
        from unittest import mock
        from app.knowledge_engine import semantic_provider as sp

        class Up:
            name = "ollama"

            def describe(self):
                return {"provider": "ollama", "model": "qwen2.5:7b-instruct", "model_version": "qwen2.5:7b-instruct",
                        "base_url": "http://127.0.0.1:11434", "temperature": 0.0}

        real = sp.discover_providers(load_config())
        reachable = [(Up(), {"available": True, "kind": "ollama"})] + [x for x in real if x[1].get("kind") != "ollama"]
        with mock.patch.dict("os.environ", {"SEMANTIC_MODE": "replay"}), \
                mock.patch.object(sp, "discover_providers", return_value=reachable):
            adj, info = semantic_setup(load_config(), REPO)
        self.assertNotEqual(info["mode"], "LIVE")
        self.assertEqual(info["live_disabled"], "SEMANTIC_MODE=replay")

    def test_new_sections_live_outside_semantic_ai(self):
        cfg = load_config()
        for key in ("promotion_v2", "gate_file", "result_file"):
            self.assertNotIn(key, cfg["semantic_ai"])
        self.assertIn("gate_sha256", cfg["semantic_promotion_v2"])


if __name__ == "__main__":
    unittest.main()
