"""Codex CLI adapter."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Mapping

from .base import ParsedRequest, PreparedCommand, ProviderAdapter


class CodexAdapter(ProviderAdapter):
    provider_id = "codex"
    prompt_delivery = "stdin"
    binary_override_env = "CODEX_BIN"
    preflight_binary = False
    start_ledger_before_prompt = True

    def usage(self) -> str:
        return "codex-shim: usage: codex-shim.sh <prompt-source> [extra codex-exec args]"

    def parse(self, argv: list[str], env: Mapping[str, str], home: Path) -> ParsedRequest:
        self.require_args(argv, 1, self.usage())
        model = "codex-default"
        config = home / ".codex" / "config.toml"
        try:
            for line in config.read_text(encoding="utf-8").splitlines():
                match = re.match(r'^model\s*=\s*"(.*)"', line)
                if match:
                    model = match.group(1)
                    break
        except OSError:
            pass
        previous = ""
        for argument in argv[1:]:
            if previous in {"-m", "--model"}:
                model = argument
            if argument.startswith("--model="):
                model = argument.removeprefix("--model=")
            elif argument.startswith("-m="):
                model = argument.removeprefix("-m=")
            elif argument.startswith("model="):
                model = argument.removeprefix("model=")
            previous = argument
        return ParsedRequest(source=argv[0], model=model, extra_args=argv[1:])

    def resolve_binary(self, env: Mapping[str, str], home: Path) -> str | None:
        return env.get("CODEX_BIN") or "codex"

    def missing_binary_message(self) -> str:
        return "codex-shim: codex CLI not found"

    def prepare(
        self,
        request: ParsedRequest,
        binary: str,
        prompt: bytes,
        env: Mapping[str, str],
        preflight_data: Mapping[str, str],
    ) -> PreparedCommand:
        child_env = dict(env)
        attributes = child_env.get("OTEL_RESOURCE_ATTRIBUTES", "")
        model_attribute = f"gen_ai.request.model={request.model}"
        child_env["OTEL_RESOURCE_ATTRIBUTES"] = f"{attributes},{model_attribute}" if attributes else model_attribute
        args = ["exec", "--skip-git-repo-check"]
        if self.unrestricted(env):
            args.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            args.extend(["--sandbox", "workspace-write"])
        args.extend(request.extra_args)
        return PreparedCommand(
            argv=[binary, *args],
            env=child_env,
            stdin=prompt,
            sanitized_args=self.sanitize_args(args),
        )
