"""Persistent worker process (Milestone 3).

Polls the shared job store for ready queued jobs and processes them
sequentially (CPU-bounded, ADR-006). Run as a separate process:

    python -m clipforge_worker.worker_process [--storage storage] [--poll 0.5]

API requests never block on this worker; submission only enqueues.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from clipforge_jobs import JobStore
from clipforge_providers import ProviderBundle, get_providers
from clipforge_worker.processor import JobProcessor

logger = logging.getLogger("clipforge.worker")


class PersistentWorker:
    def __init__(self, store: JobStore, providers: ProviderBundle, poll_seconds: float = 0.5) -> None:
        self.store = store
        self.processor = JobProcessor(store, providers)
        self.poll_seconds = poll_seconds

    def run_once(self) -> bool:
        """Claim and process a single ready job. Returns True if a job was processed."""
        for record in self.store.list_ready_queued():
            claimed = self.store.claim(record.job_id)
            if claimed is None:
                continue  # claimed by another worker/process; isolation preserved
            self.processor.process(claimed.job_id)
            return True
        return False

    def run_forever(self) -> None:
        logger.info("worker_started mode=%s poll=%.2fs", "mock", self.poll_seconds)
        try:
            while True:
                if not self.run_once():
                    time.sleep(self.poll_seconds)
        except KeyboardInterrupt:
            logger.info("worker_stopped (keyboard interrupt)")


def main() -> int:
    parser = argparse.ArgumentParser(description="ClipForge persistent worker (mock mode).")
    parser.add_argument("--storage", default="storage", help="Storage root directory.")
    parser.add_argument("--poll", type=float, default=0.5, help="Poll interval in seconds when idle.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    providers = get_providers()  # mock by default; live raises explicitly (ADR-004)
    worker = PersistentWorker(JobStore(Path(args.storage)), providers, poll_seconds=args.poll)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
