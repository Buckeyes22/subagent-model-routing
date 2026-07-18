"""Run-store privacy, prompt retention, and cleanup tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.run_store import RunStore, cleanup_runs, find_run, list_runs  # noqa: E402


class RunStoreTests(unittest.TestCase):
    def test_private_atomic_documents_and_prompt_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = {"HOME": directory, "XDG_STATE_HOME": str(Path(directory) / "state")}
            store = RunStore.create(env, "dispatch-one")
            store.write_json("run.json", {"state": "created"})
            store.record_request("prompt.md", b"sensitive\n", retain_prompt=False)
            self.assertEqual(0o700, store.path.stat().st_mode & 0o777)
            self.assertEqual(0o600, store.artifact("run.json").stat().st_mode & 0o777)
            self.assertFalse(store.artifact("prompt.md").exists())
            request = json.loads(store.artifact("request.json").read_text(encoding="utf-8"))
            self.assertEqual(10, request["promptSource"]["bytes"])
            self.assertFalse(request["promptSource"]["retained"])
            store.record_request("prompt.md", b"sensitive\n", retain_prompt=True)
            self.assertEqual(b"sensitive\n", store.artifact("prompt.md").read_bytes())

    def test_list_find_and_explicit_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = {"HOME": directory, "XDG_STATE_HOME": str(Path(directory) / "state")}
            RunStore.create(env, "dispatch-one")
            RunStore.create(env, "dispatch-two")
            self.assertEqual(2, len(list_runs(env)))
            self.assertEqual("dispatch-one", find_run(env, "dispatch-o").name)
            removed = cleanup_runs(env, older_than_seconds=None, remove_all=True)
            self.assertEqual(2, len(removed))
            self.assertEqual([], list_runs(env))


if __name__ == "__main__":
    unittest.main()
