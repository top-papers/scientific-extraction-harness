"""Deterministic, disabled-by-default scheduling for human-gated improvement runs.

The scheduler is deliberately an offline boundary: callers supply metrics and metadata;
it never executes candidate code, invokes an LLM, or performs network work.  A scheduler
run only creates an immutable review packet.  Promotion requires a separate, matching
``ReviewEvent(action='approve')`` supplied by a human workflow.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Iterator, Mapping
from uuid import uuid4

from .gates import GatePolicy, GateResult
from .improvement import CandidateManifest
from .improvement_loop import ImprovementController, ImprovementDecision, ReviewPacket
from .review import ReviewEvent, ReviewStore


class SchedulerError(RuntimeError):
    """Raised when scheduling cannot safely proceed."""


@dataclass(frozen=True)
class Schedule:
    """A deterministic trigger.  Schedules are disabled unless explicitly enabled."""

    enabled: bool = False
    interval_seconds: int | None = None
    due_at: str | None = None

    def __post_init__(self) -> None:
        if self.interval_seconds is not None and (
            isinstance(self.interval_seconds, bool) or self.interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be a positive integer")
        if self.interval_seconds is not None and self.due_at is not None:
            raise ValueError("choose interval_seconds or due_at, not both")
        if self.due_at is not None:
            _parse_time(self.due_at)

    def is_due(self, now: str, last_run_at: str | None) -> bool:
        if not self.enabled:
            return False
        current = _parse_time(now)
        if self.due_at is not None:
            return last_run_at is None and current >= _parse_time(self.due_at)
        if self.interval_seconds is None:
            return False
        return last_run_at is None or current >= _parse_time(last_run_at) + timedelta(seconds=self.interval_seconds)


@dataclass(frozen=True)
class PromotionReceipt:
    candidate_id: str
    run_id: str
    review_event_id: str
    reviewer_id: str
    note: str


@dataclass(frozen=True)
class ScheduledReviewPacket(ReviewPacket):
    """A persisted review packet carrying its scheduler run identity."""

    run_id: str


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise SchedulerError("timestamps must be ISO strings")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchedulerError("invalid timestamp") from exc
    if result.tzinfo is None:
        raise SchedulerError("timestamps must include timezone")
    return result.astimezone(timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(v) for v in value]
    return value


class Scheduler:
    """Persisted, single-flight scheduler for one candidate manifest."""

    def __init__(
        self,
        state_path: Path | str,
        schedule: Schedule | None = None,
        *,
        lock_timeout: float = 0.0,
        max_runs: int = 1,
        review_store: ReviewStore | None = None,
    ) -> None:
        if max_runs <= 0:
            raise ValueError("max_runs must be positive")
        if lock_timeout < 0:
            raise ValueError("lock_timeout must be non-negative")
        self.state_path = Path(state_path)
        self.lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        self.schedule = schedule or Schedule()
        self.lock_timeout = lock_timeout
        self.max_runs = max_runs
        self.review_store = review_store

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"version": 1, "last_run_at": None, "runs": [], "approvals": []}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1:
                raise ValueError
            if not isinstance(value.get("runs"), list) or not isinstance(value.get("approvals"), list):
                raise ValueError
            return value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SchedulerError("scheduler state is corrupt") from exc

    def _save(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError as exc:
            raise SchedulerError("cannot persist scheduler state") from exc

    @contextmanager
    def _lock(self) -> Iterator[None]:
        started = time.monotonic()
        while True:
            try:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
                with self.lock_path.open("x", encoding="utf-8"):
                    break
            except FileExistsError:
                if time.monotonic() - started >= self.lock_timeout:
                    raise SchedulerError("scheduler lock timeout")
                time.sleep(0.01)
            except OSError as exc:
                raise SchedulerError("cannot acquire scheduler lock") from exc
        try:
            yield
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _run_id(candidate_id: str, trigger: str) -> str:
        return "run-" + hashlib.sha256((candidate_id + "|" + trigger).encode()).hexdigest()

    def run(
        self,
        manifest: CandidateManifest,
        metrics: Mapping[str, Any],
        candidate_metadata: Mapping[str, Any],
        policy: GatePolicy,
        *,
        now: str | None = None,
        force: bool = False,
    ) -> ReviewPacket | None:
        """Create one packet when due. ``force`` never bypasses the disabled default."""
        if not isinstance(manifest, CandidateManifest):
            raise TypeError("manifest must be a CandidateManifest")
        if not isinstance(metrics, Mapping) or not isinstance(candidate_metadata, Mapping):
            raise TypeError("metrics and candidate_metadata must be mappings")
        current = now or _now()
        _parse_time(current)
        with self._lock():
            state = self._load()
            if not self.schedule.enabled:
                return None
            trigger = self.schedule.due_at or current
            run_id = self._run_id(manifest.candidate_id, trigger)
            for record in state["runs"]:
                if record.get("run_id") == run_id:
                    return self._packet_from_record(record)
            if len(state["runs"]) >= self.max_runs:
                return None
            if not force and not self.schedule.is_due(current, state.get("last_run_at")):
                return None
            base = ImprovementController().review_packet(manifest, metrics, candidate_metadata, policy)
            packet = ScheduledReviewPacket(
                base.candidate_id, base.parent_id, base.hypothesis, base.gate_result,
                base.metric_deltas, base.recommendation, base.decision, run_id,
            )
            record = self._packet_record(packet, run_id, current)
            state["runs"].append(record)
            state["last_run_at"] = current
            self._save(state)
            return packet

    def approve(self, packet: ReviewPacket, event: ReviewEvent) -> PromotionReceipt:
        """Validate a fresh human approval; this is the only promotion boundary."""
        if not isinstance(packet, ReviewPacket) or not isinstance(event, ReviewEvent):
            raise TypeError("packet and event are required")
        if event.action != "approve" or event.candidate_id != packet.candidate_id:
            raise SchedulerError("approval does not match candidate or is not an approval")
        if not event.reviewer_id.strip() or not event.note or not event.note.strip():
            raise SchedulerError("approval requires reviewer identity and a non-empty note")
        run_id = packet.run_id if isinstance(packet, ScheduledReviewPacket) else self._packet_run_id(packet)
        if event.run_id != run_id:
            raise SchedulerError("approval does not match run")
        with self._lock():
            state = self._load()
            if run_id not in {r.get("run_id") for r in state["runs"]}:
                raise SchedulerError("approval is stale")
            if event.review_event_id in set(state["approvals"]):
                raise SchedulerError("approval has already been replayed")
            if self.review_store is not None:
                existing = self.review_store.for_candidate(packet.candidate_id, run_id)
                if any(item.review_event_id == event.review_event_id for item in existing):
                    raise SchedulerError("approval has already been replayed")
                self.review_store.append(event)
            state["approvals"].append(event.review_event_id)
            self._save(state)
        return PromotionReceipt(packet.candidate_id, run_id, event.review_event_id, event.reviewer_id, event.note or "")

    def _packet_record(self, packet: ReviewPacket, run_id: str, created_at: str) -> dict[str, Any]:
        gate = packet.gate_result
        return {"run_id": run_id, "created_at": created_at, "candidate_id": packet.candidate_id,
                "packet": {"candidate_id": packet.candidate_id, "parent_id": packet.parent_id,
                "hypothesis": packet.hypothesis, "metric_deltas": _json(packet.metric_deltas),
                "recommendation": packet.recommendation, "gate_result": {"passed": gate.passed,
                "gate_results": _json(gate.gate_results), "failures": list(gate.failures),
                "diagnostics": _json(gate.diagnostics)}}}

    def _packet_from_record(self, record: Mapping[str, Any]) -> ReviewPacket:
        raw = record.get("packet")
        if not isinstance(raw, Mapping):
            raise SchedulerError("scheduler run packet is corrupt")
        gate_raw = raw.get("gate_result")
        if not isinstance(gate_raw, Mapping):
            raise SchedulerError("scheduler gate result is corrupt")
        try:
            gate = GateResult(bool(gate_raw["passed"]), gate_raw["gate_results"],
                              tuple(gate_raw["failures"]), gate_raw["diagnostics"], GatePolicy())
            decision = ImprovementDecision(str(raw["candidate_id"]), raw.get("parent_id"),
                                           str(raw["hypothesis"]), gate, raw.get("metric_deltas", {}),
                                           str(raw["recommendation"]))
            return ScheduledReviewPacket(decision.candidate_id, decision.parent_id, decision.hypothesis,
                                          gate, decision.metric_deltas, decision.recommendation, decision,
                                          str(record["run_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise SchedulerError("scheduler run packet is corrupt") from exc

    def _packet_run_id(self, packet: ReviewPacket) -> str:
        state = self._load()
        matches = []
        for record in state["runs"]:
            p = record.get("packet", {})
            if p.get("candidate_id") == packet.candidate_id and p.get("hypothesis") == packet.hypothesis:
                matches.append(record)
        if len(matches) != 1:
            raise SchedulerError("packet is stale or not produced by this scheduler")
        return str(matches[0]["run_id"])


__all__ = ["Schedule", "Scheduler", "SchedulerError", "PromotionReceipt"]
