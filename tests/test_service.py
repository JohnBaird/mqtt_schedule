from datetime import datetime

from mqtt_schedule.service import PeriodicJob, ServiceConfig, ServiceRunner, seconds_until_next_minute


class FakeApplication:
    def __init__(self) -> None:
        self.calls: list[datetime] = []

    def run_schedule_tick(self, now: datetime):
        self.calls.append(now)
        return None


def test_seconds_until_next_minute() -> None:
    now = datetime(2026, 6, 20, 11, 45, 12, 500000)
    seconds = seconds_until_next_minute(now)
    assert abs(seconds - 47.5) < 0.001


def test_service_runner_runs_once_per_minute_boundary() -> None:
    app = FakeApplication()
    moments = iter(
        [
            datetime(2026, 6, 20, 11, 44, 59),
            datetime(2026, 6, 20, 11, 45, 0),
            datetime(2026, 6, 20, 11, 45, 0),
            datetime(2026, 6, 20, 11, 45, 1),
        ]
    )

    runner: ServiceRunner | None = None

    def clock() -> datetime:
        nonlocal runner
        try:
            return next(moments)
        except StopIteration:
            assert runner is not None
            runner.stop()
            return datetime(2026, 6, 20, 11, 45, 2)

    runner = ServiceRunner(
        app,
        clock=clock,
        sleeper=lambda _: None,
        config=ServiceConfig(run_immediately=False),
    )

    runner.run_forever()

    assert app.calls == [datetime(2026, 6, 20, 11, 45, 0)]


def test_service_runner_can_run_immediately() -> None:
    app = FakeApplication()
    moments = iter([datetime(2026, 6, 20, 11, 45, 12)])

    runner: ServiceRunner | None = None

    def clock() -> datetime:
        nonlocal runner
        try:
            return next(moments)
        except StopIteration:
            assert runner is not None
            runner.stop()
            return datetime(2026, 6, 20, 11, 45, 13)

    runner = ServiceRunner(
        app,
        clock=clock,
        sleeper=lambda _: None,
        config=ServiceConfig(run_immediately=True),
    )

    runner.run_forever()

    assert app.calls == [datetime(2026, 6, 20, 11, 45, 12)]


def test_service_runner_executes_periodic_jobs() -> None:
    app = FakeApplication()
    job_calls: list[str] = []
    moments = iter(
        [
            datetime(2026, 6, 20, 11, 45, 12),
            datetime(2026, 6, 20, 11, 45, 13),
            datetime(2026, 6, 20, 11, 45, 15),
        ]
    )

    runner: ServiceRunner | None = None

    def clock() -> datetime:
        nonlocal runner
        try:
            return next(moments)
        except StopIteration:
            assert runner is not None
            runner.stop()
            return datetime(2026, 6, 20, 11, 45, 16)

    runner = ServiceRunner(
        app,
        clock=clock,
        sleeper=lambda _: None,
        periodic_jobs=[
            PeriodicJob(
                job_id="refresh",
                interval_seconds=2,
                fn=lambda: job_calls.append("refresh"),
                run_immediately=True,
            )
        ],
    )

    runner.run_forever()

    assert job_calls == ["refresh", "refresh"]
