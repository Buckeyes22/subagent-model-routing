"""OpenCode CLI adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from model_routing.process import run_bounded_capture

from .base import ParsedRequest, PreparedCommand, ProviderAdapter


class OpenCodeAdapter(ProviderAdapter):
    provider_id = "opencode"
    prompt_delivery = "stdin"
    binary_override_env = "OPENCODE_BIN"
    missing_binary_ledger = "finished"
    start_ledger_before_prompt = True

    def usage(self) -> str:
        return "opencode-shim: usage: opencode-shim.sh <provider/model> <prompt-source> [extra opencode-run args]"

    def parse(self, argv: list[str], env: Mapping[str, str], home: Path) -> ParsedRequest:
        self.require_args(argv, 2, self.usage())
        return ParsedRequest(source=argv[1], model=argv[0], extra_args=argv[2:])

    def resolve_binary(self, env: Mapping[str, str], home: Path) -> str | None:
        if env.get("OPENCODE_BIN"):
            return env["OPENCODE_BIN"]
        discovered = self.which("opencode", env)
        if discovered:
            return discovered
        fallback = home / ".opencode" / "bin" / "opencode"
        return str(fallback) if os.access(fallback, os.X_OK) else None

    def missing_binary_message(self) -> str:
        return "opencode-shim: opencode CLI not found"

    def preflight(
        self,
        request: ParsedRequest,
        binary: str,
        env: Mapping[str, str],
    ) -> dict[str, str]:
        if not self.unrestricted(env):
            return {}
        try:
            result = run_bounded_capture(
                [binary, "run", "--help"],
                env=dict(env),
                timeout_seconds=30,
                max_bytes=1024 * 1024,
            )
            help_text = (result.stdout + result.stderr).decode(
                "utf-8", errors="replace"
            )
        except OSError:
            help_text = ""
        if "--dangerously-skip-permissions" in help_text:
            return {"permissionFlag": "--dangerously-skip-permissions"}
        if "--auto" in help_text:
            return {"permissionFlag": "--auto"}
        return {}

    def prepare(
        self,
        request: ParsedRequest,
        binary: str,
        prompt: bytes,
        env: Mapping[str, str],
        preflight_data: Mapping[str, str],
    ) -> PreparedCommand:
        child_env = dict(env)
        if child_env.get("OPENCODE_OTLP_ENDPOINT"):
            child_env.setdefault("OPENCODE_ENABLE_TELEMETRY", "1")
            child_env.setdefault("OPENCODE_OTLP_PROTOCOL", "http/protobuf")
            child_env.setdefault("OPENCODE_RESOURCE_ATTRIBUTES", "service.name=opencode")
        args = ["run", "-m", request.model]
        permission_flag = preflight_data.get("permissionFlag")
        if permission_flag:
            args.append(permission_flag)
        args.extend(request.extra_args)
        return PreparedCommand([binary, *args], child_env, prompt, self.sanitize_args(args))
