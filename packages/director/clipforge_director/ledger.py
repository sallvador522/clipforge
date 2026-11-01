"""Live-call budget ledger (per-function caps, atomic, no network).

Used to enforce the phase limits (max 2 live transcription calls and max 2 live
director calls). Reserved BEFORE the network call; a refused reservation raises
without touching the provider.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_LIMITS = {"transcription": 2, "director": 2}


class LiveBudgetExceeded(RuntimeError):
    def __init__(self, function: str, limit: int) -> None:
        super().__init__(
            f"Live-call budget exhausted for {function!r}: limit {limit} reached. "
            "No request was attempted; a new phase needs fresh approval."
        )
        self.function = function
        self.limit = limit


class LiveCallBudget:
    def __init__(self, storage_root: str | Path, *, limits: dict[str, int] | None = None) -> None:
        self._path = Path(storage_root) / "live-call-ledger.json"
        self._lock = self._path.with_suffix(".lock")
        self._limits = dict(DEFAULT_LIMITS)
        if limits:
            self._limits.update(limits)

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
