"""Dispatch-result semantic validation stays aligned with its JSON schema."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from model_routing.result import ResultError, validate_result  # noqa: E402


def valid_result() -> dict[str, object]:
    digest = {"bytes": 0, "sha256": "0" * 64}
    return {
        "schemaVersion": 1,
        "dispatchId": "00000000-0000-4000-8000-000000000001",
        "workflowId": None,
        "taskId": None,
        "provider": "codex",
        "model": "gpt-test",
        "requestedModel": "gpt-test",
        "effort": None,
        "arguments": [],
        "providerVersion": None,
        "status": "succeeded",
        "outcome": "ok",
        "createdAt": "2026-07-10T00:00:00.000Z",
        "startedAt": "2026-07-10T00:00:00.000Z",
        "finishedAt": "2026-07-10T00:00:01.000Z",
        "wallMs": 1000,
        "exitCode": 0,
        "signal": None,
        "timeout": {"seconds": 1140, "expired": False},
        "sentinel": {"emitted": True, "exit": 0},
        "workspace": {"mode": "shared", "path": "/tmp", "baseSha": None, "finalSha": None},
        "output": {"stdout": dict(digest), "stderr": dict(digest)},
        "artifacts": {"result": "/tmp/result.json"},
        "integration": {"status": "not_applied", "appliedAt": None, "target": None},
    }


class ResultTests(unittest.TestCase):
    def test_valid_result_is_accepted(self) -> None:
        validate_result(valid_result())

    def test_signal_and_arguments_types_are_enforced(self) -> None:
        for field, invalid in (("signal", "SIGTERM"), ("arguments", "--model gpt-test")):
            with self.subTest(field=field):
                value = valid_result()
                value[field] = invalid
                with self.assertRaisesRegex(ResultError, field):
                    validate_result(value)


if __name__ == "__main__":
    unittest.main()
