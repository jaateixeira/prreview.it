"""The queue that writes AI reviews in the background (ADR 0025).

Two small pools of worker threads: one for the model services on the internet, one for
Previewit's own server, which reviews one work at a time. A job holds the person's key in
memory until it has run; nothing is written to disk. The workers are daemon threads, so a
restart never waits for a slow model: what was queued is picked up by
`AiReviewsService.recover` when Previewit starts again.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

from loguru import logger

from previewit.domain.ai_reviews import AiReviewId

Run = Callable[[AiReviewId, str], None]


class ThreadedAiJobs:
    def __init__(self, *, workers: int = 4, local_workers: int = 1) -> None:
        self._sizes = {False: workers, True: local_workers}
        self._queues: dict[bool, queue.Queue[tuple[AiReviewId, str]]] = {
            False: queue.Queue(),
            True: queue.Queue(),
        }
        self._run: Run | None = None
        self._started = False
        self._lock = threading.Lock()

    def bind(self, run: Run) -> None:
        """What each job does: the service is made after the queue it uses."""
        self._run = run

    def start(self, review_id: AiReviewId, key: str, *, free: bool) -> None:
        self._start_workers()
        self._queues[free].put((review_id, key))

    def wait(self) -> None:
        """Until every queued job has run (for tests)."""
        for jobs in self._queues.values():
            jobs.join()

    def _start_workers(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            for free, size in self._sizes.items():
                for number in range(size):
                    name = f"ai-review-{'local' if free else 'online'}-{number}"
                    threading.Thread(
                        target=self._work, args=(free,), name=name, daemon=True
                    ).start()

    def _work(self, free: bool) -> None:
        jobs = self._queues[free]
        while True:
            review_id, key = jobs.get()
            try:
                if self._run is not None:
                    self._run(review_id, key)
            except Exception as error:
                # Only the type: a traceback could show the key among the local variables.
                logger.error("AI review {} stopped: {}", review_id, type(error).__name__)
            finally:
                del key
                jobs.task_done()
