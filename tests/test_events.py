"""Lifecycle event envelope and global-stream tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.events import EventEmitter  # noqa: E402
from model_routing.run_store import RunStore  # noqa: E402


class EventTests(unittest.TestCase):
    def test_event_is_written_to_run_and_global_streams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env = {"HOME": directory, "XDG_STATE_HOME": str(Path(directory) / "state")}
            store = RunStore.create(env, "dispatch-one")
            event = EventEmitter(store, provider="codex", model="gpt-test").emit(
                "dispatch.output", {"channel": "stdout", "bytes": 4}
            )
            self.assertEqual("dispatch-one", event["dispatchId"])
            self.assertNotIn("content", event["data"])
            local = json.loads(store.artifact("events.jsonl").read_text(encoding="utf-8"))
            global_event = json.loads((store.state_root / "events.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(event, local)
            self.assertEqual(event, global_event)


if __name__ == "__main__":
    unittest.main()
