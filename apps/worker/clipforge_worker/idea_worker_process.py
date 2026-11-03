"""Persistent idea worker process.

Polls the idea store for approved, queued idea jobs and processes them one at
a time (CPU-bound render, ADR-006). Run separately from the editing worker so
a five-minute idea render never blocks uploads:

    python -m clipforge_worker.idea_worker_process [--storage storage] [--poll 1.0]

API requests never block on this worker; approvals only enqueue.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from clipforge_jobs.idea_store import IdeaStore
from clipforge_worker.idea_processor import IdeaProcessor

logger = logging.getLogger("clipforge.idea_worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClipForge idea worker")
    parser.add_argument("--storage", default="storage")
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    store = IdeaStore(Path(args.storage))
    processor = IdeaProcessor(store)
    logger.info("idea_worker_started storage=%s poll=%.2fs", args.storage, args.poll)
    while True:
        worked = processor.run_once()
        if args.once:
            return 0
        if not worked:
            time.sleep(max(0.2, args.poll))


if __name__ == "__main__":
    raise SystemExit(main())
