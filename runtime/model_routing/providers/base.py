"""Typed provider-adapter contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Mapping

from model_routing.errors import UsageError


@dataclass(slots=True)
class ParsedRequest:
    source: str
    model: str
    extra_args: list[str]
    has_model_override: bool = False
    adapter_data: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class PreparedCommand:
    argv: list[str]
    env: dict[str, str]
    stdin: bytes | None
    sanitized_args: list[str]


class ProviderAdapter:
    provider_id = ""
    prompt_delivery = "stdin"
    binary_override_env: str | None = None
    preflight_binary = True
    missing_binary_ledger = "none"
    start_ledger_before_prompt = False

    def usage(self) -> str:
        raise NotImplementedError

    def parse(self, argv: list[str], env: Mapping[str, str], home: Path) -> ParsedRequest:
        raise NotImplementedError

    def resolve_binary(self, env: Mapping[str, str], home: Path) -> str | None:
        raise NotImplementedError

    def missing_binary_message(self) -> str:
        raise NotImplementedError

    def preflight(
        self,
        request: ParsedRequest,
        binary: str,
        env: Mapping[str, str],
    ) -> dict[str, str]:
        return {}

    def prepare(
        self,
        request: ParsedRequest,
        binary: str,
        prompt: bytes,
        env: Mapping[str, str],
        preflight_data: Mapping[str, str],
    ) -> PreparedCommand:
        raise NotImplementedError

    @staticmethod
    def require_args(argv: list[str], count: int, usage: str) -> None:
        if len(argv) < count:
            raise UsageError(usage)

    @staticmethod
    def which(command: str, env: Mapping[str, str]) -> str | None:
        return shutil.which(command, path=env.get("PATH"))

    @staticmethod
    def unrestricted(env: Mapping[str, str]) -> bool:
        return env.get("SUBAGENT_MODEL_ROUTING_UNRESTRICTED", "1") == "1"

    @staticmethod
    def prompt_text(prompt: bytes) -> str:
        # Bash command substitution strips every trailing newline. Decode with
        # replacement so malformed prompt bytes cannot crash lifecycle cleanup.
        return prompt.rstrip(b"\n").decode("utf-8", errors="replace")

    @staticmethod
    def sanitize_args(arguments: list[str]) -> list[str]:
        sensitive_names = ("api-key", "apikey", "token", "secret", "password", "authorization")
        sanitized: list[str] = []
        redact_next = False
        for argument in arguments:
            lowered = argument.lower()
            if redact_next:
                sanitized.append("<redacted>")
                redact_next = False
                continue
            if argument.startswith("-") and any(name in lowered for name in sensitive_names):
                if "=" in argument:
                    sanitized.append(argument.split("=", 1)[0] + "=<redacted>")
                else:
                    sanitized.append(argument)
                    redact_next = True
                continue
            sanitized.append(argument)
        return sanitized
