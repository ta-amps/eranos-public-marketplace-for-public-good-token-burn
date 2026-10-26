"""Traced Backend wrapper: logs every Tessera queue and store verb to JSON Lines."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tessera import Backend, ChildSpec, Lease, Receipt, TaskSpec, TaskView
from tessera.clock import Clock

from eranos.log import TraceWriter


class TracedBackend:
    def __init__(
        self,
        inner: Backend,
        *,
        backend: str,
        trace_path: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._inner = inner
        self._trace = TraceWriter(trace_path)
        self.backend = backend
        if clock is not None:
            self.clock = clock

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def enqueue(self, spec: TaskSpec) -> str:
        task_id = self._inner.enqueue(spec)
        self._trace.write("enqueued", task_id=task_id, queue=spec.queue, backend=self.backend)
        return task_id

    def claim(
        self,
        queue: str,
        worker: str,
        *,
        kinds: Sequence[str] | None = None,
        effect_classes: Sequence[str] | None = None,
    ) -> Lease | None:
        lease = self._inner.claim(queue, worker, kinds=kinds, effect_classes=effect_classes)
        if lease is not None:
            self._trace.write(
                "claimed",
                task_id=lease.task_id,
                queue=queue,
                worker=worker,
                lease_id=lease.fencing_token,
                backend=self.backend,
            )
        return lease

    def heartbeat(self, task_id: str, fencing_token: int) -> Lease:
        return self._inner.heartbeat(task_id, fencing_token)

    def split(self, task_id: str, fencing_token: int, children: Sequence[ChildSpec]) -> list[str]:
        ids = self._inner.split(task_id, fencing_token, children)
        self._trace.write(
            "split", task_id=task_id, lease_id=fencing_token, children=ids, backend=self.backend
        )
        return ids

    def submit(
        self,
        task_id: str,
        fencing_token: int,
        output: dict[str, Any],
        *,
        idempotency_key: str,
        ok: bool = True,
        error: str | None = None,
    ) -> Receipt:
        receipt = self._inner.submit(
            task_id, fencing_token, output, idempotency_key=idempotency_key, ok=ok, error=error
        )
        cost = output.get("cost_usd") if isinstance(output.get("cost_usd"), int | float) else None
        self._trace.write(
            "submitted",
            task_id=task_id,
            lease_id=fencing_token,
            ok=ok,
            receipt_hash=receipt.receipt_hash,
            state_after=receipt.state_after,
            cost_usd=cost,
            backend=self.backend,
        )
        return receipt

    def cancel(self, task_id: str, reason: str = "") -> TaskView:
        view = self._inner.cancel(task_id, reason)
        self._trace.write("cancelled", task_id=task_id, reason=reason, backend=self.backend)
        return view

    def park(
        self, task_id: str, fencing_token: int, *, reason: str, resume_within: float | None = None
    ) -> TaskView:
        view = self._inner.park(task_id, fencing_token, reason=reason, resume_within=resume_within)
        self._trace.write(
            "parked", task_id=task_id, lease_id=fencing_token, reason=reason, backend=self.backend
        )
        return view

    def resume(self, task_id: str, value: dict[str, Any], *, park: int | None = None) -> TaskView:
        view = self._inner.resume(task_id, value, park=park)
        self._trace.write("resumed", task_id=task_id, backend=self.backend)
        return view

    def close(self) -> None:
        self._inner.close()
