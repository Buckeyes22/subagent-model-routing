"""Regression tests for Claude Code's Stop-hook enforcement boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DAG_TRIPWIRE = ROOT / "plugins" / "subagent-model-routing-claude" / "hooks" / "dag-tripwire.py"


def user_entry(text: str) -> dict[str, object]:
    return {"type": "user", "message": {"content": text}}


def bash_entry(command: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command}}
            ]
        },
    }


class ClaudeTripwireTests(unittest.TestCase):
    def run_dag_hook(self, command: str) -> dict[str, object] | None:
        entries = [
            user_entry("command-name>/subagent-model-routing-claude:dag-routing run"),
            bash_entry(command),
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as transcript:
            for entry in entries:
                transcript.write(json.dumps(entry) + "\n")
            transcript.flush()
            result = subprocess.run(
                [sys.executable, str(DAG_TRIPWIRE)],
                input=json.dumps(
                    {"stop_hook_active": False, "transcript_path": transcript.name}
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_run_and_resume_reject_non_claude_host_declarations(self) -> None:
        for command in (
            "model-routing workflow run workflow.json --host copilot",
            "model-routing workflow resume 123 --host=codex",
            "bash -lc 'model-routing workflow run workflow.json --host copilot'",
        ):
            with self.subTest(command=command):
                response = self.run_dag_hook(command)
                self.assertEqual("block", response["decision"] if response else None)
                self.assertIn("HOST BOUNDARY", str(response["reason"]))

    def test_run_and_resume_allow_the_claude_host_declaration(self) -> None:
        for command in (
            "model-routing workflow run workflow.json --host claude",
            "model-routing workflow resume 123 --host=claude",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.run_dag_hook(command))

    def test_runner_text_that_is_not_executed_is_silent(self) -> None:
        self.assertIsNone(
            self.run_dag_hook(
                "grep 'model-routing workflow run workflow.json --host copilot' README.md"
            )
        )


if __name__ == "__main__":
    unittest.main()
