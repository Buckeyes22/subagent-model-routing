#!/usr/bin/env python3
"""Validate published schemas and representative runtime documents."""

from __future__ import annotations

import json
import importlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT))

from model_routing.doctor import run_doctor  # noqa: E402
from model_routing.provider_setup import load_install_specs  # noqa: E402
from tests.shim_test_support import ShimSandbox  # noqa: E402


jsonschema = importlib.import_module("jsonschema")


def schema(name: str) -> dict[str, object]:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def validate(name: str, instance: object) -> None:
    document = schema(name)
    jsonschema.Draft202012Validator.check_schema(document)
    jsonschema.Draft202012Validator(
        document,
        format_checker=jsonschema.FormatChecker(),
    ).validate(instance)


def main() -> int:
    registry = json.loads((ROOT / "config" / "provider-registry.json").read_text(encoding="utf-8"))
    validate("provider-registry.schema.json", registry)
    installers = json.loads((ROOT / "config" / "provider-installers.json").read_text(encoding="utf-8"))
    validate("provider-installers.schema.json", installers)
    load_install_specs(ROOT, system_name="Linux")
    load_install_specs(ROOT, system_name="Darwin")
    for workflow in sorted((ROOT / "examples").glob("*/workflow.json")):
        validate("workflow.schema.json", json.loads(workflow.read_text(encoding="utf-8")))

    report = run_doctor(
        ROOT,
        {"PATH": os.environ.get("PATH", "")},
        installation_only=True,
    )
    validate("doctor-result.schema.json", report)

    sandbox = ShimSandbox()
    try:
        sandbox.install_provider("codex")
        prompt = sandbox.prompt("schema validation\n")
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "model-routing"), "dispatch", "codex", str(prompt)],
            cwd=ROOT,
            env=sandbox.environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))
        run = sandbox.run_directories()[0]
        validate("dispatch-result.schema.json", json.loads((run / "result.json").read_text(encoding="utf-8")))
        for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
            validate("lifecycle-event.schema.json", json.loads(line))
    finally:
        sandbox.cleanup()

    print("all schemas and representative runtime documents are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
