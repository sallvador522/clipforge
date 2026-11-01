"""Live-call budget ledger and one-shot execution authorization.

The ledger is the last line of defence before a billable HTTP request. It fails
closed: an unreadable or structurally invalid ledger refuses reservations rather
than silently resetting counters. A reservation is atomic, happens immediately
before the network call, and is never released automatically after an uncertain
outcome. A lock left by a crashed process is reported explicitly and must be
recovered manually after verifying that no call is in flight.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_LIMITS = {"transcription": 2, "director": 2}
LIMIT_ENV_VARS = {
    "transcription": "CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT",
    "director": "CLIPFORGE_LIVE_DIRECTOR_LIMIT",
}


class LedgerIntegrityError(RuntimeError):
    """The ledger cannot be trusted; no reservation is permitted."""


class LedgerLockedError(RuntimeError):
    """Another process holds the ledger lock; no reservation is permitted."""


class LiveCallNotAuthorizedError(RuntimeError):
    """A live provider call was attempted without a valid one-shot authorization."""


def _env_limit(function: str) -> int | None:
    env_var = LIMIT_ENV_VARS[function]
    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{env_var} must be a positive integer, got {raw!r}.") from exc
    if value < 1:
        raise ValueError(f"{env_var} must be a positive integer, got {raw!r}.")
    return value


def _validate_counts(data: Any, path: Path) -> dict[str, int]:
    if not isinstance(data, dict):
        raise LedgerIntegrityError(
            f"Ledger {path} must contain a JSON object; refusing reservations."
        )
    unknown = set(data) - set(DEFAULT_LIMITS)
    if unknown:
        raise LedgerIntegrityError(
            f"Ledger {path} contains unknown function(s) {sorted(unknown)}; refusing reservations."
        )
    counts: dict[str, int] = {}
    for function, value in data.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LedgerIntegrityError(
                f"Ledger {path} has an invalid count for {function!r}: {value!r}; "
                "refusing reservations."
            )
        counts[function] = value
    return counts


class LiveBudgetExceeded(RuntimeError):
    def __init__(self, function: str, limit: int) -> None:
        env_var = LIMIT_ENV_VARS.get(function)
        hint = (
            f" Increase {env_var} and reset the ledger only with approval."
            if env_var
            else " A new phase needs fresh approval."
        )
        super().__init__(
            f"Live-call budget exhausted for {function!r}: limit {limit} reached. "
            f"No request was attempted.{hint}"
        )
        self.function = function
        self.limit = limit


class LiveCallBudget:
    def __init__(self, storage_root: str | Path, *, limits: dict[str, int] | None = None) -> None:
        self._path = Path(storage_root) / "live-call-ledger.json"
        self._lock = self._path.with_suffix(".lock")
        self._limits = dict(DEFAULT_LIMITS)
        for function in self._limits:
            override = _env_limit(function)
            if override is not None:
                self._limits[function] = override
        if limits:
            self._limits.update(limits)

    @property
    def limits(self) -> dict[str, int]:
        """Configured caps (defaults + environment overrides + explicit limits)."""
        return dict(self._limits)

    def _read(self) -> dict[str, int]:
        # A missing ledger is a valid empty ledger (new phase).
        if not self._path.is_file():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LedgerIntegrityError(
                f"Ledger {self._path} could not be read; refusing reservations."
            ) from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LedgerIntegrityError(
                f"Ledger {self._path} is not valid JSON; refusing reservations."
            ) from exc
        return _validate_counts(data, self._path)

    def reserve(self, function: str) -> int:
        """Atomically reserve one call. Raises before any network request on failure."""
        limit = self._limits.get(function)
        if limit is None:
            raise ValueError(f"Unknown budget function {function!r}.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self._lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise LedgerLockedError(
                f"Ledger lock {self._lock} exists. No reservation was made. "
                "Do not delete the lock until you have verified that no live call is in flight."
            ) from exc
        except OSError as exc:
            raise LedgerIntegrityError(
                f"Could not acquire ledger lock {self._lock}; refusing reservations."
            ) from exc

        try:
            counts = self._read()
            used = counts.get(function, 0)
            if used >= limit:
                raise LiveBudgetExceeded(function, limit)
            counts[function] = used + 1
            tmp = self._path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(counts, indent=2), encoding="utf-8")
                os.replace(tmp, self._path)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                raise LedgerIntegrityError(
                    f"Ledger {self._path} could not be written atomically; refusing reservations."
                ) from exc
            return counts[function]
        finally:
            os.close(fd)
            self._lock.unlink(missing_ok=True)

    def used(self, function: str) -> int:
        return self._read().get(function, 0)


class LiveCallAuthorization:
    """One-shot authorization for one logical live request.

    The provider reserves the corresponding ledger slot through this object
    immediately before its HTTP POST. The same authorization cannot reserve a
    second time, so a retry or duplicate call cannot silently spend twice.
    """

    def __init__(self, budget: LiveCallBudget, function: str) -> None:
        if function not in DEFAULT_LIMITS:
            raise ValueError(f"Unknown budget function {function!r}.")
        self._budget = budget
        self._function = function
        self._reserved = False

    @classmethod
    def from_storage(cls, storage_root: str | Path, function: str) -> "LiveCallAuthorization":
        return cls(LiveCallBudget(storage_root), function)

    @property
    def function(self) -> str:
        return self._function

    @property
    def reserved(self) -> bool:
        return self._reserved

    def reserve(self) -> int:
        if self._reserved:
            raise LiveCallNotAuthorizedError(
                "This authorization has already reserved its single logical request; "
                "a retry is not permitted."
            )
        count = self._budget.reserve(self._function)
        self._reserved = True
        return count
