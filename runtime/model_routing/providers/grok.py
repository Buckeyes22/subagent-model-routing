"""Grok Build CLI adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .base import ParsedRequest, PreparedCommand, ProviderAdapter


class GrokAdapter(ProviderAdapter):
    provider_id = "grok"
    prompt_delivery = "argv"
    binary_override_env = "GROK_BIN"

    def usage(self) -> str:
        return "grok-shim: usage: grok-shim.sh <prompt-source> [extra grok args]"

    def parse(self, argv: list[str], env: Mapping[str, str], home: Path) -> ParsedRequest:
        self.require_args(argv, 1, self.usage())
        model = "grok-4.5"
        has_model = False
        previous = ""
        for argument in argv[1:]:
            if previous in {"-m", "--model"}:
                model = argument
                has_model = True
            if argument.startswith("--model="):
                model = argument.removeprefix("--model=")
                has_model = True
            elif argument.startswith("-m="):
                model = argument.removeprefix("-m=")
                has_model = True
            previous = argument
        return ParsedRequest(argv[0], model, argv[1:], has_model)

    def resolve_binary(self, env: Mapping[str, str], home: Path) -> str | None:
        return env.get("GROK_BIN") or self.which("grok", env)

    def missing_binary_message(self) -> str:
        return "grok-shim: Grok Build CLI not found (install from https://docs.x.ai/build/overview)"

    def prepare(
        self,
        request: ParsedRequest,
        binary: str,
        prompt: bytes,
        env: Mapping[str, str],
        preflight_data: Mapping[str, str],
    ) -> PreparedCommand:
        args = ["--no-auto-update", "--no-alt-screen"]
        if self.unrestricted(env):
            args.append("--always-approve")
        if not request.has_model_override:
            args.extend(["-m", request.model])
        args.extend(request.extra_args)
        args.extend(["--output-format", "plain", "-p", self.prompt_text(prompt)])
        return PreparedCommand([binary, *args], dict(env), None, self.sanitize_args(args[:-1] + ["<prompt>"]))
