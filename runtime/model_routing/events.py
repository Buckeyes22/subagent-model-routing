"""Structured dispatch lifecycle events."""

from __future__ import annotations

from typing import Any, Callable
import uuid

from .run_store import RunStore, append_jsonl, utc_now


EventCallback = Callable[[dict[str, Any], RunStore], None]


class EventEmitter:
    def __init__(
        self,
        store: RunStore,
        *,
        provider: str,
        model: str,
        workflow_id: str | None = None,
        task_id: str | None = None,
        callback: EventCallback | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.model = model
        self.workflow_id = workflow_id
        self.task_id = task_id
        self.callback = callback

    def emit(self, event: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        envelope = {
            "schemaVersion": 1,
            "eventId": str(uuid.uuid4()),
            "event": event,
            "timestamp": utc_now(),
            "dispatchId": self.store.dispatch_id,
            "workflowId": self.workflow_id,
            "taskId": self.task_id,
            "provider": self.provider,
            "model": self.model,
            "data": data or {},
        }
        append_jsonl(self.store.artifact("events.jsonl"), envelope)
        append_jsonl(self.store.state_root / "events.jsonl", envelope)
        if self.callback is not None:
            self.callback(envelope, self.store)
        return envelope
