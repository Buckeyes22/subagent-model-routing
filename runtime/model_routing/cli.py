"""Command-line interface for dispatch and run inspection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .dispatch import dispatch_legacy
from .doctor import run_doctor
from .provider_setup import ProviderSetupError, run_provider_setup
from .registry import RegistryError, load_registry
from .run_store import cleanup_runs, find_run, list_runs
from .scheduler import (
    WorkflowRunError,
    cancel_workflow,
    list_workflows,
    resume_workflow,
    run_workflow,
    show_workflow,
)
from .workflow import WorkflowError
from .workspace import WorkspaceError, apply_run, discard_run, inspect_run, load_worktree_metadata


REPO_ROOT = Path(__file__).resolve().parents[2]


def _runs_list() -> int:
    for path in list_runs(os.environ):
        result_path = path / "result.json"
        run_path = path / "run.json"
        try:
            value = json.loads((result_path if result_path.is_file() else run_path).read_text(encoding="utf-8"))
            print(f"{path.name}\t{value.get('provider', '-')}\t{value.get('model', '-')}\t{value.get('status', value.get('state', '-'))}")
        except (OSError, json.JSONDecodeError):
            print(f"{path.name}\t-\t-\tcorrupt")
    return 0


def _runs_show(dispatch_id: str) -> int:
    try:
        path = find_run(os.environ, dispatch_id)
    except FileNotFoundError as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 1
    target = path / "result.json"
    if not target.is_file():
        target = path / "run.json"
    try:
        sys.stdout.write(target.read_text(encoding="utf-8"))
        return 0
    except OSError as exc:
        print(f"model-routing: cannot read run: {exc}", file=sys.stderr)
        return 1


def _runs_logs(dispatch_id: str, channel: str) -> int:
    try:
        path = find_run(os.environ, dispatch_id)
    except FileNotFoundError as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 1
    names = ["stdout.log", "stderr.log"] if channel == "both" else [f"{channel}.log"]
    for name in names:
        target = path / name
        try:
            sys.stdout.buffer.write(target.read_bytes())
        except OSError as exc:
            print(f"model-routing: cannot read {name}: {exc}", file=sys.stderr)
            return 1
    return 0


def _parse_age(value: str) -> float:
    raw = value.strip().lower()
    if raw.endswith("d"):
        raw = raw[:-1]
    days = float(raw)
    if days < 0:
        raise argparse.ArgumentTypeError("age must be non-negative")
    return days


def _runs_cleanup(days: float | None, remove_all: bool) -> int:
    if not remove_all and days is None:
        print("model-routing: runs cleanup requires --older-than DAYS or --all", file=sys.stderr)
        return 2
    removed = cleanup_runs(
        os.environ,
        older_than_seconds=None if days is None else days * 86400,
        remove_all=remove_all,
    )
    for path in removed:
        print(path.name)
    return 0


def _runs_diff(dispatch_id: str) -> int:
    try:
        path = find_run(os.environ, dispatch_id)
        target = path / "changes.patch"
        if not target.is_file():
            raise FileNotFoundError(f"run {dispatch_id!r} has no captured changes")
        sys.stdout.buffer.write(target.read_bytes())
        return 0
    except (FileNotFoundError, OSError) as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 1


def _runs_apply(dispatch_id: str, target: Path, commits: bool) -> int:
    try:
        outcome = apply_run(os.environ, dispatch_id, target, apply_commits=commits)
    except WorkspaceError as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(outcome.__dict__ if hasattr(outcome, "__dict__") else {
        "status": outcome.status,
        "appliedAt": outcome.appliedAt,
        "target": outcome.target,
        "appliedCommits": outcome.appliedCommits,
        "conflictedFiles": outcome.conflictedFiles,
        "method": outcome.method,
        "identity": outcome.identity,
        "message": outcome.message,
    }, indent=2, sort_keys=True))
    return 1 if outcome.status == "conflicted" else 0


def _runs_discard(dispatch_id: str, yes: bool) -> int:
    try:
        metadata = load_worktree_metadata(os.environ, dispatch_id)
        if not yes:
            print(f"branch: {metadata.branch}")
            print(f"worktree: {metadata.path}")
            try:
                details = inspect_run(os.environ, dispatch_id).get("changeset") or {}
                print(f"changed files: {details.get('changedFileCount', 'unknown')}")
            except WorkspaceError:
                pass
            if not sys.stdin.isatty() or input("Discard this owned worktree and branch? [y/N] ").strip().lower() not in {"y", "yes"}:
                print("model-routing: discard cancelled", file=sys.stderr)
                return 2
        discard_run(os.environ, dispatch_id, yes=True)
        return 0
    except WorkspaceError as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 1


def _doctor(
    provider: str | None,
    installation_only: bool,
    live_auth: bool,
    discover_models: bool,
    json_output: bool,
) -> int:
    try:
        report = run_doctor(
            REPO_ROOT,
            os.environ,
            provider=provider,
            installation_only=installation_only,
            live_auth=live_auth,
            discover_models=discover_models,
        )
    except ValueError as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 2
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for check in report["checks"]:
            scope = f"/{check['provider']}" if check.get("provider") else ""
            print(f"[{check['status']}] {check['category']}{scope} {check['id']}: {check['summary']}")
            if check.get("remediation") and check["status"] != "PASS":
                print(f"  remediation: {check['remediation']}")
        print(f"doctor: {report['status']} ({report['summary']})")
    registry_failure = any(
        check["status"] == "FAIL" and check["id"].startswith("runtime.registry")
        for check in report["checks"]
    )
    if registry_failure:
        return 2
    return 1 if report["summary"]["fail"] else 0


def _setup_providers(dry_run: bool, no_color: bool) -> int:
    try:
        return run_provider_setup(
            REPO_ROOT,
            os.environ,
            dry_run=dry_run,
            no_color=no_color,
        )
    except ProviderSetupError as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 2


def _workflow_registry() -> dict[str, object]:
    return load_registry(REPO_ROOT / "config" / "provider-registry.json")


def _workflow_run(path: Path, host: str) -> int:
    try:
        state = run_workflow(
            path,
            host=host,
            repo_root=Path.cwd(),
            env=os.environ,
            registry=_workflow_registry(),
        )
    except (WorkflowError, WorkflowRunError, RegistryError, OSError, json.JSONDecodeError) as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0 if state["status"] == "succeeded" else 1


def _workflow_resume(workflow_id: str, host: str | None) -> int:
    try:
        state = resume_workflow(
            workflow_id,
            repo_root=Path.cwd(),
            env=os.environ,
            registry=_workflow_registry(),
            declared_host=host,
        )
    except (WorkflowError, WorkflowRunError, RegistryError, OSError, json.JSONDecodeError) as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0 if state["status"] == "succeeded" else 1


def _workflow_list(json_output: bool) -> int:
    states = list_workflows(os.environ)
    if json_output:
        print(json.dumps(states, indent=2, sort_keys=True))
    else:
        for state in states:
            print(f"{state.get('workflowId', '-') }\t{state.get('status', '-')}\t{state.get('name', '-')}")
    return 0


def _workflow_show(workflow_id: str) -> int:
    try:
        state = show_workflow(os.environ, workflow_id)
    except WorkflowRunError as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def _workflow_cancel(workflow_id: str) -> int:
    try:
        state = cancel_workflow(os.environ, workflow_id)
    except WorkflowRunError as exc:
        print(f"model-routing: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="model-routing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dispatch = subparsers.add_parser("dispatch")
    dispatch.add_argument("provider", choices=("codex", "claude", "grok", "kimi", "opencode"))
    dispatch.add_argument("provider_args", nargs=argparse.REMAINDER)
    internal = subparsers.add_parser("_shim", add_help=False)
    internal.add_argument("provider", choices=("codex", "claude", "grok", "kimi", "opencode"))
    internal.add_argument("provider_args", nargs=argparse.REMAINDER)
    runs = subparsers.add_parser("runs")
    run_commands = runs.add_subparsers(dest="runs_command", required=True)
    run_commands.add_parser("list")
    show = run_commands.add_parser("show")
    show.add_argument("dispatch_id")
    logs = run_commands.add_parser("logs")
    logs.add_argument("dispatch_id")
    logs.add_argument("--channel", choices=("stdout", "stderr", "both"), default="stdout")
    cleanup = run_commands.add_parser("cleanup")
    cleanup.add_argument("--older-than", type=_parse_age, metavar="DAYS")
    cleanup.add_argument("--all", action="store_true")
    diff = run_commands.add_parser("diff")
    diff.add_argument("dispatch_id")
    apply = run_commands.add_parser("apply")
    apply.add_argument("dispatch_id")
    apply.add_argument("--target", type=Path, default=Path.cwd())
    apply.add_argument("--commits", action="store_true", help="cherry-pick captured commits before applying working changes")
    discard = run_commands.add_parser("discard")
    discard.add_argument("dispatch_id")
    discard.add_argument("--yes", action="store_true")
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--json", action="store_true", dest="json_output")
    doctor.add_argument("--provider", choices=("codex", "claude", "grok", "kimi", "opencode"))
    doctor.add_argument("--installation-only", action="store_true")
    doctor.add_argument("--live-auth", action="store_true")
    doctor.add_argument("--discover-models", action="store_true")
    setup = subparsers.add_parser("setup")
    setup_commands = setup.add_subparsers(dest="setup_command", required=True)
    setup_providers = setup_commands.add_parser("providers")
    setup_providers.add_argument("--dry-run", action="store_true")
    setup_providers.add_argument("--no-color", action="store_true")
    workflow = subparsers.add_parser("workflow")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_run = workflow_commands.add_parser("run")
    workflow_run.add_argument("path", type=Path)
    workflow_run.add_argument("--host", choices=("claude", "codex", "copilot"), required=True)
    workflow_list = workflow_commands.add_parser("list")
    workflow_list.add_argument("--json", action="store_true", dest="json_output")
    workflow_show = workflow_commands.add_parser("show")
    workflow_show.add_argument("workflow_id")
    workflow_resume = workflow_commands.add_parser("resume")
    workflow_resume.add_argument("workflow_id")
    workflow_resume.add_argument("--host", choices=("claude", "codex", "copilot"))
    workflow_cancel = workflow_commands.add_parser("cancel")
    workflow_cancel.add_argument("workflow_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("model-routing requires Python 3.11 or newer", file=sys.stderr)
        return 127
    args = build_parser().parse_args(argv)
    if args.command in {"dispatch", "_shim"}:
        return dispatch_legacy(args.provider, args.provider_args)
    if args.command == "doctor":
        return _doctor(
            args.provider,
            args.installation_only,
            args.live_auth,
            args.discover_models,
            args.json_output,
        )
    if args.command == "setup":
        return _setup_providers(args.dry_run, args.no_color)
    if args.command == "workflow":
        if args.workflow_command == "run":
            return _workflow_run(args.path, args.host)
        if args.workflow_command == "list":
            return _workflow_list(args.json_output)
        if args.workflow_command == "show":
            return _workflow_show(args.workflow_id)
        if args.workflow_command == "resume":
            return _workflow_resume(args.workflow_id, args.host)
        return _workflow_cancel(args.workflow_id)
    if args.runs_command == "list":
        return _runs_list()
    if args.runs_command == "show":
        return _runs_show(args.dispatch_id)
    if args.runs_command == "logs":
        return _runs_logs(args.dispatch_id, args.channel)
    if args.runs_command == "diff":
        return _runs_diff(args.dispatch_id)
    if args.runs_command == "apply":
        return _runs_apply(args.dispatch_id, args.target, args.commits)
    if args.runs_command == "discard":
        return _runs_discard(args.dispatch_id, args.yes)
    return _runs_cleanup(args.older_than, args.all)


if __name__ == "__main__":
    raise SystemExit(main())
