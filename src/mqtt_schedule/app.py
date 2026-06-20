from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .domain import ControllerTarget, DueCommand, IrrigationDecision, ScheduleEntry, SunTimes
from .scheduler import EvaluationResult, ScheduleEvaluator


class ScheduleRepository(Protocol):
    def list_schedules(self) -> list[ScheduleEntry]:
        ...


class ControllerRepository(Protocol):
    def list_controllers(self) -> list[ControllerTarget]:
        ...


class SunTimesProvider(Protocol):
    def get_sun_times(self, now: datetime) -> SunTimes:
        ...


class IrrigationPolicyService(Protocol):
    def decide(self, now: datetime) -> IrrigationDecision:
        ...


class CommandPublisher(Protocol):
    def publish_due_command(self, command: DueCommand) -> None:
        ...


@dataclass
class RuntimeSnapshot:
    evaluated_at: datetime
    command_count: int
    evaluation_results: list[EvaluationResult] | None = None


class SchedulerApplication:
    def __init__(
        self,
        *,
        schedule_repository: ScheduleRepository,
        controller_repository: ControllerRepository,
        sun_times_provider: SunTimesProvider,
        irrigation_policy: IrrigationPolicyService,
        publisher: CommandPublisher,
        evaluator: ScheduleEvaluator,
    ) -> None:
        self.schedule_repository = schedule_repository
        self.controller_repository = controller_repository
        self.sun_times_provider = sun_times_provider
        self.irrigation_policy = irrigation_policy
        self.publisher = publisher
        self.evaluator = evaluator

    def run_schedule_tick(self, now: datetime) -> RuntimeSnapshot:
        schedules = self.schedule_repository.list_schedules()
        controllers = self.controller_repository.list_controllers()
        sun_times = self.sun_times_provider.get_sun_times(now)

        evaluation_results = self.evaluator.evaluate_with_explanations(
            now=now,
            schedules=schedules,
            controllers=controllers,
            sun_times=sun_times,
            irrigation_policy=self.irrigation_policy.decide,
        )

        commands = [item.command for item in evaluation_results if item.command is not None]
        for command in commands:
            self.publisher.publish_due_command(command)

        return RuntimeSnapshot(
            evaluated_at=now,
            command_count=len(commands),
            evaluation_results=evaluation_results,
        )
