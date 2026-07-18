"""Runtime exceptions with stable shim-facing exit semantics."""

from __future__ import annotations


class RoutingError(RuntimeError):
    """Base class for expected routing failures."""


class UsageError(RoutingError):
    """The public shim invocation is invalid."""


class PromptError(RoutingError):
    """The requested prompt source cannot be read."""


class ProviderNotFoundError(RoutingError):
    """A provider executable cannot be resolved."""
