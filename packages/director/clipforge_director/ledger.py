"""Live-call budget ledger (per-function caps, atomic, no network).

Defaults are the phase limits (2 live transcription + 2 live director calls).
For explicit local testing, each cap can be raised with an environment variable:

    CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT=100
    CLIPFORGE_LIVE_DIRECTOR_LIMIT=25

A reservation is written immediately before the network call; a refused
reservation raises without touching the provider. The ledger is never reset
automatically — raising a limit does not erase usage history.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_LIMITS = {"transcription": 2, "director": 2}
LIMIT_ENV_VARS = {
    "transcription": "CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT",
    "director": "CLIPFORGE_LIVE_DIRECTOR_LIMIT",
}


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
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}

    def reserve(self, function: str) -> int:
        """Atomically reserve one call. Raises LiveBudgetExceeded when over the cap."""
        limit = self._limits.get(function)
        if limit is None:
            raise ValueError(f"Unknown budget function {function!r}.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self._lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("Live-call ledger is locked by another process.") from exc
        try:
            counts = self._read()
            used = counts.get(function, 0)
            if used >= limit:
                raise LiveBudgetExceeded(function, limit)
            counts[function] = used + 1
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(counts, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
            return counts[function]
        finally:
            os.close(fd)
            self._lock.unlink(missing_ok=True)

    def used(self, function: str) -> int:
        return self._read().get(function, 0)
