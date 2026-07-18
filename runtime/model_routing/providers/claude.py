"""Claude Code CLI adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .base import ParsedRequest, PreparedCommand, ProviderAdapter


class ClaudeAdapter(ProviderAdapter):
    provider_id = "claude"
    prompt_delivery = "argv"
    binary_override_env = "CLAUDE_BIN"

    def usage(self) -> str:
        return "claude-shim: usage: claude-shim.sh <prompt-source> [extra claude args]"

    def parse(self, argv: list[str], env: Mapping[str, str], home: Path) -> ParsedRequest:
        self.require_args(argv, 1, self.usage())
        model = "sonnet"
        has_model = False
        previous = ""
        for argument in argv[1:]:
            if previous == "--model":
                model = argument
                has_model = True
            if argument.startswith("--model="):
                model = argument.removeprefix("--model=")
                has_model = True
            previous = argument
        return ParsedRequest(argv[0], model, argv[1:], has_model)

    def resolve_binary(self, env: Mapping[str, str], home: Path) -> str | None:
        return env.get("CLAUDE_BIN") or self.which("claude", env)

    def missing_binary_message(self) -> str:
        return "claude-shim: Claude Code CLI not found (see https://code.claude.com/docs/en/cli-reference)"

    def prepare(
        self,
        request: ParsedRequest,
        binary: str,
        prompt: bytes,
        env: Mapping[str, str],
        preflight_data: Mapping[str, str],
    ) -> PreparedCommand:
        args = ["-p", "--no-session-persistence"]
        if self.unrestricted(env):
            args.append("--dangerously-skip-permissions")
        if not request.has_model_override:
            args.extend(["--model", request.model])
        args.extend(request.extra_args)
        args.extend(["--output-format", "text", "--", self.prompt_text(prompt)])
        return PreparedCommand([binary, *args], dict(env), None, self.sanitize_args(args[:-1] + ["<prompt>"]))
