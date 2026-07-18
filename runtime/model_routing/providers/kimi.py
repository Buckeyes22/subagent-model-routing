"""Kimi Code CLI provider adapter."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Mapping

from model_routing.errors import UsageError

from .base import ParsedRequest, PreparedCommand, ProviderAdapter


_PROMPT_MODE_RESERVED_FLAGS = ("-p", "--prompt", "--output-format")
_PROMPT_MODE_INCOMPATIBLE_FLAGS = ("-y", "--yolo", "--auto")


class KimiAdapter(ProviderAdapter):
    provider_id = "kimi"
    prompt_delivery = "argv"
    binary_override_env = "KIMI_BIN"

    def usage(self) -> str:
        return "kimi-shim: usage: kimi-shim.sh <prompt-source> [extra kimi args]"

    @staticmethod
    def _configured_model(env: Mapping[str, str], home: Path) -> str:
        environment_model = env.get("KIMI_MODEL_NAME")
        if environment_model:
            return environment_model
        root = Path(env.get("KIMI_CODE_HOME", str(home / ".kimi-code"))).expanduser()
        try:
            data = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return "kimi-default"
        model = data.get("default_model")
        return model if isinstance(model, str) and model else "kimi-default"

    def parse(self, argv: list[str], env: Mapping[str, str], home: Path) -> ParsedRequest:
        self.require_args(argv, 1, self.usage())
        for argument in argv[1:]:
            if argument in _PROMPT_MODE_INCOMPATIBLE_FLAGS:
                raise UsageError(
                    f"kimi-shim: {argument} cannot be combined with Kimi Code prompt mode"
                )
            if argument in _PROMPT_MODE_RESERVED_FLAGS or any(
                argument.startswith(f"{flag}=")
                for flag in _PROMPT_MODE_RESERVED_FLAGS
            ):
                raise UsageError(
                    f"kimi-shim: {argument.split('=', 1)[0]} is managed by the shim"
                )
        model = self._configured_model(env, home)
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
        del home
        return env.get("KIMI_BIN") or self.which("kimi", env)

    def missing_binary_message(self) -> str:
        return "kimi-shim: Kimi Code CLI not found (see https://moonshotai.github.io/kimi-code/)"

    def prepare(
        self,
        request: ParsedRequest,
        binary: str,
        prompt: bytes,
        env: Mapping[str, str],
        preflight_data: Mapping[str, str],
    ) -> PreparedCommand:
        del preflight_data
        child_env = dict(env)
        child_env.setdefault("KIMI_CODE_NO_AUTO_UPDATE", "1")
        args = [*request.extra_args, "--output-format", "text", "--prompt", self.prompt_text(prompt)]
        return PreparedCommand(
            [binary, *args],
            child_env,
            None,
            self.sanitize_args(args[:-1] + ["<prompt>"]),
        )
