"""Qwen Code CLI provider adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from model_routing.errors import UsageError

from .base import ParsedRequest, PreparedCommand, ProviderAdapter


_PROMPT_MODE_RESERVED_FLAGS = ("-p", "--prompt", "--output-format")
_PROMPT_MODE_INCOMPATIBLE_FLAGS = ("-y", "--yolo", "--approval-mode")


class QwenAdapter(ProviderAdapter):
    provider_id = "qwen"
    prompt_delivery = "argv"
    binary_override_env = "QWEN_BIN"

    def usage(self) -> str:
        return "qwen-shim: usage: qwen-shim.sh <prompt-source> [extra qwen args]"

    @staticmethod
    def _configured_model(env: Mapping[str, str], home: Path) -> str:
        environment_model = env.get("QWEN_MODEL")
        if environment_model:
            return environment_model
        root = Path(env.get("QWEN_CODE_HOME", str(home / ".qwen"))).expanduser()
        try:
            data = json.loads((root / "settings.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        model = data.get("model")
        if isinstance(model, dict):
            model = model.get("name")
        if isinstance(model, str) and model:
            return model
        try:
            dotenv_lines = (root / ".env").read_text(encoding="utf-8").splitlines()
        except OSError:
            return "qwen-default"
        dotenv = {}
        for line in dotenv_lines:
            key, separator, value = line.partition("=")
            if separator:
                dotenv[key.strip()] = value.strip().strip("'\"")
        model = dotenv.get("QWEN_MODEL") or dotenv.get("OPENAI_MODEL")
        return model if isinstance(model, str) and model else "qwen-default"

    def parse(self, argv: list[str], env: Mapping[str, str], home: Path) -> ParsedRequest:
        self.require_args(argv, 1, self.usage())
        for argument in argv[1:]:
            if argument in _PROMPT_MODE_INCOMPATIBLE_FLAGS or any(
                argument.startswith(f"{flag}=")
                for flag in _PROMPT_MODE_INCOMPATIBLE_FLAGS
            ):
                raise UsageError(
                    f"qwen-shim: {argument.split('=', 1)[0]} is managed by the shim"
                )
            if argument in _PROMPT_MODE_RESERVED_FLAGS or any(
                argument.startswith(f"{flag}=")
                for flag in _PROMPT_MODE_RESERVED_FLAGS
            ):
                raise UsageError(
                    f"qwen-shim: {argument.split('=', 1)[0]} is managed by the shim"
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
        return env.get("QWEN_BIN") or self.which("qwen", env)

    def missing_binary_message(self) -> str:
        return "qwen-shim: Qwen Code CLI not found (see https://github.com/QwenLM/qwen-code)"

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
        args = [*request.extra_args]
        if self.unrestricted(env):
            args.append("--yolo")
        args.extend(["--output-format", "text", "--prompt", self.prompt_text(prompt)])
        return PreparedCommand(
            [binary, *args],
            child_env,
            None,
            self.sanitize_args(args[:-1] + ["<prompt>"]),
        )
