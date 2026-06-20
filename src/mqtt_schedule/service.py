from __future__ import annotations

import logging
import signal
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import sleep
from typing import Callable

from .app import SchedulerApplication


Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class ServiceConfig:
    poll_interval_seconds: float = 0.25
    run_immediately: bool = False


@dataclass
class PeriodicJob:
    job_id: str
    interval_seconds: int
    fn: Callable[[], None]
    run_immediately: bool = False
    last_run_epoch: float | None = None


class ServiceRunner:
    def __init__(
        self,
        application: SchedulerApplication,
        *,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        config: ServiceConfig | None = None,
        periodic_jobs: list[PeriodicJob] | None = None,
    ) -> None:
        self.application = application
        self.clock = clock or datetime.now
        self.sleeper = sleeper or sleep
        self.config = config or ServiceConfig()
        self.periodic_jobs = periodic_jobs or []
        self._stop_event = threading.Event()
        self._last_tick_key: str | None = None
        self.logger = logging.getLogger("mqtt_schedule.service")

    def stop(self) -> None:
        self._stop_event.set()

    def run_forever(self) -> int:
        if self.config.run_immediately:
            now = self.clock()
            self.logger.info("service_tick trigger=run_immediately at=%s", now.isoformat())
            self._run_tick(now)

        while not self._stop_event.is_set():
            now = self.clock()
            fire_key = self._minute_key(now)
            if fire_key != self._last_tick_key and self._is_minute_boundary(now):
                self.logger.info("service_tick trigger=minute_boundary at=%s", now.isoformat())
                self._run_tick(now)

            self._run_periodic_jobs(now)

            self.sleeper(self.config.poll_interval_seconds)

        return 0

    def _run_tick(self, now: datetime) -> None:
        self.application.run_schedule_tick(now)
        self._last_tick_key = self._minute_key(now)

    @staticmethod
    def _minute_key(now: datetime) -> str:
        return now.strftime("%Y%m%d%H%M")

    @staticmethod
    def _is_minute_boundary(now: datetime) -> bool:
        return now.second == 0

    def _run_periodic_jobs(self, now: datetime) -> None:
        now_epoch = now.timestamp()
        for job in self.periodic_jobs:
            if job.last_run_epoch is None:
                if job.run_immediately:
                    self._run_periodic_job(job)
                    job.last_run_epoch = now_epoch
                else:
                    job.last_run_epoch = now_epoch
                continue

            if (now_epoch - job.last_run_epoch) >= job.interval_seconds:
                self._run_periodic_job(job)
                job.last_run_epoch = now_epoch

    @staticmethod
    def _run_periodic_job(job: PeriodicJob) -> None:
        try:
            logging.getLogger("mqtt_schedule.service").info("periodic_job_start job_id=%s", job.job_id)
            job.fn()
            logging.getLogger("mqtt_schedule.service").info("periodic_job_complete job_id=%s", job.job_id)
        except Exception:
            logging.getLogger("mqtt_schedule.service").exception(
                "periodic_job_failed job_id=%s",
                job.job_id,
            )
            return


class SignalAwareService:
    def __init__(self, runner: ServiceRunner) -> None:
        self.runner = runner

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)

    def _handle_signal(self, signum, frame) -> None:
        self.runner.stop()


def seconds_until_next_minute(now: datetime) -> float:
    next_minute = (now.replace(second=0, microsecond=0) + timedelta(minutes=1))
    return max(0.0, (next_minute - now).total_seconds())
