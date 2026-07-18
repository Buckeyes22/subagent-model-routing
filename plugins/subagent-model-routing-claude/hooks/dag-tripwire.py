#!/usr/bin/env python3
"""dag-tripwire.py — Stop-hook backstop for the dag-routing TRANSPORT leak.

Fires a one-time checkpoint (decision:block) when, in the CURRENT turn:
  1. the /dag-routing slash command was invoked OR the subagent-model-routing skill is active
     (including plugin-namespaced skill attribution), AND
  2. >= 1 shim was dispatched DIRECTLY — Bash `*-shim.sh` (non-pong), or
     Agent subagent_type in the namespaced plugin shims (or legacy bare shim names), AND
  3. ZERO `Workflow` tool calls happened.

That triple is the transport leak: a DAG was requested but executed as loose shells /
direct Agent dispatch instead of a `Workflow`. It does NOT fire on:
  - dev sessions that merely mention the skill (keys on command marker / skill attribution, not mentions),
  - mid-setup turns or clarifying pauses (requires an actual direct-shim dispatch),
  - correct runs (a Workflow call silences it).
It DOES fire on a deliberate "not-a-DAG -> flat direct dispatch" inside the command/skill
context; the checkpoint text lets you confirm that and continue — that's by design, since
the leak and that legitimate case share an observable signature.

Fail-safe: any parse problem -> exit 0 (never blocks spuriously).
Loop-safe: if stop_hook_active is set, exit 0.
Disable: disable/remove the subagent-model-routing plugin, or delete its hooks/hooks.json "Stop" entry.
"""
import sys, json, os, re, shlex

CMD_MARKERS = ("command-name>/dag-routing", "command-name>/subagent-model-routing-claude:dag-routing")
SKILL_ATTRIBUTIONS = {"subagent-model-routing-claude", "subagent-model-routing-claude:subagent-model-routing"}
SHIM_TYPES = {
    "codex-shim",
    "opencode-shim",
    "grok-shim",
    "kimi-shim",
    "subagent-model-routing-claude:codex-shim",
    "subagent-model-routing-claude:opencode-shim",
    "subagent-model-routing-claude:grok-shim",
    "subagent-model-routing-claude:kimi-shim",
}
SHIM_INVOCATION_RE = re.compile(
    r"(?:^|[;&|(`]|\n)\s*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
    r"(?:(?:\S*/)?(?:bash|sh)\s+(?:-\w+\s+)*|env\s+(?:\S+\s+)*|timeout\s+\S+\s+)?"
    r"[\"']?(?:\S*/)?(?:codex|opencode|grok|kimi)-shim\.sh[\"']?(?:\s|$)",
    re.IGNORECASE,
)
SHIM_BASENAME_RE = re.compile(r"^(codex|opencode|grok|kimi)-shim\.sh$", re.IGNORECASE)
MODEL_ROUTING_BASENAME_RE = re.compile(r"^model-routing$", re.IGNORECASE)
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")


def _shim_basename(token):
    token = token.strip("\"'")
    return bool(SHIM_BASENAME_RE.match(os.path.basename(token)))


def _is_assignment(token):
    return bool(ASSIGNMENT_RE.match(token))


def _token_basename(token):
    return os.path.basename(token.strip("\"'")).lower()


def _segment_invokes_shim(tokens):
    i = 0
    while i < len(tokens) and _is_assignment(tokens[i]):
        i += 1

    while i < len(tokens):
        base = _token_basename(tokens[i])

        if base in {"exec", "command", "nohup", "then", "do", "else", "elif", "if", "while", "until", "time", "!", "{", "("}:
            i += 1
            continue

        if base == "env":
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
            while i < len(tokens) and _is_assignment(tokens[i]):
                i += 1
            continue

        if base == "timeout":
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
            if i < len(tokens):
                i += 1
            continue

        if base in {"bash", "sh", "zsh"}:
            i += 1
            command_string = False
            while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "-":
                if "c" in tokens[i].lstrip("-"):
                    command_string = True
                i += 1
            if command_string and i < len(tokens):
                return shim_invoked(tokens[i])
            break

        break

    return i < len(tokens) and _shim_basename(tokens[i])


def _command_segments(cmd):
    segment = []
    quote = None
    escaped = False
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        nxt = cmd[i + 1] if i + 1 < len(cmd) else ""

        if escaped:
            segment.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\":
            segment.append(ch)
            escaped = True
            i += 1
            continue
        if quote:
            segment.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            segment.append(ch)
            i += 1
            continue
        if ch == "$" and nxt == "(":
            yield "".join(segment)
            segment = []
            i += 2
            continue
        if ch in {";", "|", "\n", "`", ")"}:
            yield "".join(segment)
            segment = []
            if ch == "|" and nxt == "|":
                i += 2
            else:
                i += 1
            continue
        if ch == "&":
            yield "".join(segment)
            segment = []
            i += 2 if nxt == "&" else 1
            continue
        segment.append(ch)
        i += 1
    yield "".join(segment)


def shim_invoked(cmd):
    for segment in _command_segments(str(cmd)):
        if not segment.strip():
            continue
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            if SHIM_INVOCATION_RE.search(segment):
                return True
            continue
        if _segment_invokes_shim(tokens):
            return True
    return False


def _workflow_runner_call(tokens):
    for index, token in enumerate(tokens):
        if not MODEL_ROUTING_BASENAME_RE.match(_token_basename(token)):
            continue
        if index > 0 and _token_basename(tokens[0]) not in {
            "env", "exec", "command", "nohup", "timeout", "python", "python3",
            "python3.11", "python3.12", "python3.13",
        }:
            continue
        tail = tokens[index + 1:]
        if len(tail) < 2 or tail[0] != "workflow" or tail[1] not in {"run", "resume"}:
            continue
        host = None
        for position, argument in enumerate(tail[2:]):
            if argument.startswith("--host="):
                host = argument.split("=", 1)[1]
                break
            if argument == "--host" and position + 3 < len(tail):
                host = tail[position + 3]
                break
        return tail[1], host
    return None


def workflow_runner_calls(cmd):
    calls = []
    for segment in _command_segments(str(cmd)):
        if not segment.strip():
            continue
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            continue
        if tokens and _token_basename(tokens[0]) in {"bash", "sh", "zsh"}:
            for index, token in enumerate(tokens[1:], start=1):
                if "c" in token.lstrip("-") and index + 1 < len(tokens):
                    calls.extend(workflow_runner_calls(tokens[index + 1]))
                    break
        call = _workflow_runner_call(tokens)
        if call is not None:
            calls.append(call)
    return calls


def is_real_user_prompt(e):
    """A genuine human prompt, not a tool-result user message and not a subagent sidechain."""
    if e.get("type") != "user" or e.get("isSidechain"):
        return False
    if "toolUseResult" in e:
        return False
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    if isinstance(c, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
    return False


def tool_uses(e):
    if e.get("type") != "assistant" or e.get("isSidechain"):
        return
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield b


def dag_context_invoked(turn):
    """Was the command or subagent-model-routing skill active in this turn?"""
    for e in turn:
        if e.get("attributionSkill") in SKILL_ATTRIBUTIONS:
            return True
        if is_real_user_prompt(e):
            dumped = json.dumps(e)
            if any(marker in dumped for marker in CMD_MARKERS):
                return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("stop_hook_active"):
        return 0
    tp = data.get("transcript_path")
    if not tp:
        return 0
    try:
        entries = [json.loads(l) for l in open(tp, encoding="utf-8") if l.strip()]
    except Exception:
        return 0

    # Scope to the current turn: from the last genuine user prompt to end-of-file.
    start = None
    for i in range(len(entries) - 1, -1, -1):
        if is_real_user_prompt(entries[i]):
            start = i
            break
    if start is None:
        return 0
    turn = entries[start:]

    # 1) Was /dag-routing invoked, or was the subagent-model-routing skill active this turn?
    invoked = dag_context_invoked(turn)
    if not invoked:
        return 0

    # 2) Tally Workflow vs. direct shim dispatch among main-loop tool calls this turn.
    workflow_used = False
    direct_shim = False
    runner_host_violation = None
    for e in turn:
        for b in tool_uses(e):
            name = b.get("name")
            inp = b.get("input") or {}
            if name == "Workflow":
                workflow_used = True
            elif name == "Agent" and inp.get("subagent_type") in SHIM_TYPES:
                direct_shim = True
            elif name == "Bash":
                cmd = str(inp.get("command", ""))
                low = cmd.lower()
                for action, host in workflow_runner_calls(cmd):
                    if host != "claude":
                        runner_host_violation = (action, host)
                if shim_invoked(cmd) and not (re.search(r"\bpong\.md\b", low) or "reply with exactly" in low):
                    direct_shim = True

    if runner_host_violation is not None:
        action, host = runner_host_violation
        reason = (
            "dag-routing HOST BOUNDARY: Claude observed `model-routing workflow "
            f"{action}` with --host {host!r}. Shared-runner execution from Claude must "
            "declare `--host claude`; the runner then rejects Claude-provider tasks. "
            "Use native Claude Workflow for graphs containing Claude work."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0

    if workflow_used or not direct_shim:
        return 0

    # 3) Leak signature confirmed -> one-time checkpoint fed back to the model.
    reason = (
        "dag-routing TRIPWIRE: /dag-routing or the subagent-model-routing skill was active this turn and shims were "
        "dispatched DIRECTLY (Bash/Agent) with NO `Workflow` tool call. Per the skill's §0 this is "
        "the TRANSPORT LEAK: a DAG must run via Workflow({scriptPath}), not loose shells / direct "
        "Agent dispatch / inline Opus. ACTION: if this is a DAG, redo it via the Workflow tool. If you "
        "DELIBERATELY concluded it is NOT a DAG and used Part B flat direct dispatch on "
        "purpose, state that explicitly and continue."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
