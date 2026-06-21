from datetime import datetime
import logging
import signal

from mqtt_schedule.service import (
    PeriodicJob,
    ServiceConfig,
    ServiceRunner,
    ServiceShutdown,
    SignalAwareService,
    seconds_until_next_minute,
)


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


def test_service_runner_logs_tick_and_periodic_job(caplog) -> None:
    caplog.set_level(logging.INFO)
    app = FakeApplication()
    job_calls: list[str] = []
    moments = iter(
        [
            datetime(2026, 6, 20, 11, 44, 59),
            datetime(2026, 6, 20, 11, 45, 0),
            datetime(2026, 6, 20, 11, 45, 2),
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
            return datetime(2026, 6, 20, 11, 45, 3)

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

    messages = [record.getMessage() for record in caplog.records]
    assert any("service_tick trigger=minute_boundary" in message for message in messages)
    assert any("periodic_job_start job_id=refresh" in message for message in messages)
    assert any("periodic_job_complete job_id=refresh" in message for message in messages)


def test_signal_handler_requests_stop_and_raises_shutdown() -> None:
    runner = ServiceRunner(FakeApplication(), sleeper=lambda _: None)
    service = SignalAwareService(runner)

    try:
        service._handle_signal(signal.SIGTERM, None)
    except ServiceShutdown:
        pass
    else:
        raise AssertionError("Expected ServiceShutdown to be raised")

    assert runner._stop_event.is_set() is True


def test_service_runner_logs_shutdown(caplog) -> None:
    caplog.set_level(logging.INFO)
    app = FakeApplication()
    runner: ServiceRunner | None = None

    def clock() -> datetime:
        assert runner is not None
        runner.stop()
        raise ServiceShutdown()

    runner = ServiceRunner(
        app,
        clock=clock,
        sleeper=lambda _: None,
        config=ServiceConfig(run_immediately=False),
    )

    result = runner.run_forever()

    assert result == 0
    messages = [record.getMessage() for record in caplog.records]
    assert any("service_shutdown signal_received=true" in message for message in messages)
