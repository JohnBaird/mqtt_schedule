from __future__ import annotations

import argparse
from datetime import datetime
import logging

from .airtable_repositories import FileControllerRepository, FileScheduleRepository
from .app import ControllerRepository, FilteredControllerRepository, SchedulerApplication
from .hostinfo import HostInfoProvider
from .identity import DeviceIdentity, DeviceIdentitySettings
from .mqtt_adapter import MQTTBrokerSettings, MQTTCommandEncoder, PahoClientFactory, PahoCommandPublisher, StdoutCommandPublisher
from .scheduler import ScheduleEvaluator, SchedulerConfig
from .service import PeriodicJob, ServiceConfig, ServiceRunner, SignalAwareService, seconds_until_next_minute
from .settings import RuntimeSettings
from .weather_adapters import OpenWeatherFileSunTimesProvider, TempestFileRainPolicy
from .weather_refresh import OpenWeatherRefreshSettings, OpenWeatherRefresher, TempestRefreshSettings, TempestRefresher


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run one mqtt_schedule scheduler tick.")
    parser.add_argument("--config", help="Path to runtime JSON config file.")
    parser.add_argument("--now", help="Override current timestamp in ISO format.")
    parser.add_argument("--dry-run", action="store_true", help="Print MQTT messages instead of publishing them.")
    parser.add_argument("--explain", action="store_true", help="Print schedule match explanations for validation.")
    parser.add_argument(
        "--refresh-weather-now",
        action="store_true",
        help="Run configured OpenWeather/Tempest refresh jobs immediately before scheduler processing.",
    )
    parser.add_argument(
        "--only-destination",
        action="append",
        default=[],
        help="Further restrict matching controllers to one or more destination serials for safe commissioning.",
    )
    parser.add_argument("--service", action="store_true", help="Run as a long-lived Linux-style service.")
    parser.add_argument("--run-immediately", action="store_true", help="When used with --service, execute one tick before waiting for the next minute boundary.")
    args = parser.parse_args()

    settings = RuntimeSettings.from_json_file(args.config) if args.config else RuntimeSettings.from_env()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    source_serial = DeviceIdentity(
        DeviceIdentitySettings(
            serial_file=settings.device_serial_file,
            source_serial_override=settings.source_serial_override,
        )
    ).get_source_serial()
    host_identity = HostInfoProvider().get_identity()

    evaluator = ScheduleEvaluator(
        SchedulerConfig(
            hemisphere=settings.hemisphere,
            use_duration_sunrise=settings.use_duration_sunrise,
            use_duration_sunset=settings.use_duration_sunset,
        )
    )
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            keepalive=settings.mqtt_keepalive,
            username=settings.mqtt_username,
            password=settings.mqtt_password,
            topic_version=settings.mqtt_topic_version,
            domain=settings.mqtt_domain,
            source_serial=source_serial,
            session_client_id=host_identity.session_client_id,
            host_name=host_identity.host_name,
            ip_address=host_identity.ip_address,
            program_name=settings.program_name,
            program_version=settings.program_version,
        )
    )

    if args.dry_run:
        publisher = StdoutCommandPublisher(encoder)
        client = None
    else:
        client = PahoClientFactory.connect(encoder.settings)
        publisher = PahoCommandPublisher(client=client, encoder=encoder)

    controller_repository: ControllerRepository = build_controller_repository(
        settings=settings,
        cli_only_destinations=args.only_destination,
    )
    allowed_destinations = resolve_allowed_destinations(
        configured_destinations=settings.commissioning_only_destinations,
        cli_destinations=args.only_destination,
    )
    logger = logging.getLogger("mqtt_schedule.cli")
    if allowed_destinations:
        logger.info(
            "commissioning_filter_active destination_count=%s destinations=%s",
            len(allowed_destinations),
            ",".join(sorted(allowed_destinations)),
        )
    else:
        logger.info("commissioning_filter_inactive")

    app = SchedulerApplication(
        schedule_repository=FileScheduleRepository(settings.schedule_file),
        controller_repository=controller_repository,
        sun_times_provider=OpenWeatherFileSunTimesProvider(
            current_file=settings.openweather_current_file,
            timezone_name=settings.timezone_name,
        ),
        irrigation_policy=TempestFileRainPolicy(
            settings.tempest_data_dir,
            station_id=settings.tempest_station_id,
            rain_now_block_mm=settings.rain_now_block_mm,
            rain_24h_block_mm=settings.rain_24h_block_mm,
            rain_48h_block_mm=settings.rain_48h_block_mm,
            rain_7d_block_mm=settings.rain_7d_block_mm,
            require_latest_within_minutes=settings.require_latest_within_minutes,
        ),
        publisher=publisher,
        evaluator=evaluator,
    )

    try:
        refresh_jobs = build_weather_refresh_jobs(
            settings=settings,
        )
        if args.service:
            if args.refresh_weather_now:
                _run_weather_refresh_now(refresh_jobs)
            runner = ServiceRunner(
                app,
                config=ServiceConfig(run_immediately=args.run_immediately),
                periodic_jobs=refresh_jobs,
            )
            signals = SignalAwareService(runner)
            signals.install_signal_handlers()
            logger.info(
                "service_start now=%s seconds_until_next_minute=%.3f",
                now.isoformat(),
                seconds_until_next_minute(now),
            )
            return runner.run_forever()

        if args.refresh_weather_now:
            _run_weather_refresh_now(refresh_jobs)

        snapshot = app.run_schedule_tick(now)
        if args.explain and snapshot.evaluation_results is not None:
            _print_explanations(snapshot)
        print(f"evaluated_at={snapshot.evaluated_at.isoformat()} command_count={snapshot.command_count}")
        return 0
    finally:
        if client is not None:
            PahoClientFactory.close(client)

def _build_openweather_refresher(settings: RuntimeSettings) -> OpenWeatherRefresher | None:
    if not settings.openweather_api_key or settings.openweather_lat is None or settings.openweather_lon is None:
        return None
    return OpenWeatherRefresher(
        OpenWeatherRefreshSettings(
            base_url=settings.openweather_url,
            api_key=settings.openweather_api_key,
            lat=settings.openweather_lat,
            lon=settings.openweather_lon,
            units=settings.openweather_units,
            current_file=settings.openweather_current_file,
            forecast_file=settings.openweather_forecast_file,
        )
    )


def _build_tempest_refresher(settings: RuntimeSettings) -> TempestRefresher | None:
    if not settings.tempest_token:
        return None
    return TempestRefresher(
        TempestRefreshSettings(
            base_url=settings.tempest_base_url,
            token=settings.tempest_token,
            data_dir=settings.tempest_data_dir,
            snapshot_keep=settings.tempest_snapshot_keep,
        )
    )


def build_weather_refresh_jobs(
    *,
    settings: RuntimeSettings,
) -> list[PeriodicJob]:
    jobs: list[PeriodicJob] = []
    logger = logging.getLogger("mqtt_schedule.cli")

    openweather_refresher = _build_openweather_refresher(settings)
    if openweather_refresher is not None:
        jobs.append(
            PeriodicJob(
                job_id="openweather-refresh",
                interval_seconds=settings.weather_refresh_openweather_seconds,
                fn=openweather_refresher.refresh,
                run_immediately=settings.weather_refresh_run_immediately,
            )
        )
    else:
        logger.info("weather_refresh_disabled job_id=openweather-refresh reason=missing_configuration")

    tempest_refresher = _build_tempest_refresher(settings)
    if tempest_refresher is not None:
        jobs.append(
            PeriodicJob(
                job_id="tempest-refresh",
                interval_seconds=settings.weather_refresh_tempest_seconds,
                fn=tempest_refresher.refresh,
                run_immediately=settings.weather_refresh_run_immediately,
            )
        )
    else:
        logger.info("weather_refresh_disabled job_id=tempest-refresh reason=missing_configuration")

    for job in jobs:
        logger.info(
            "weather_refresh_configured job_id=%s interval_seconds=%s run_immediately=%s",
            job.job_id,
            job.interval_seconds,
            job.run_immediately,
        )

    return jobs


def _run_weather_refresh_now(jobs: list[PeriodicJob]) -> None:
    logger = logging.getLogger("mqtt_schedule.cli")
    if not jobs:
        logger.info("weather_refresh_now_skipped reason=no_configured_jobs")
        return
    logger.info("weather_refresh_now_start job_count=%s", len(jobs))
    for job in jobs:
        job.fn()
    logger.info("weather_refresh_now_complete job_count=%s", len(jobs))


def build_controller_repository(
    *,
    settings: RuntimeSettings,
    cli_only_destinations: list[str],
) -> ControllerRepository:
    controller_repository: ControllerRepository = FileControllerRepository(settings.controller_file)
    allowed_destinations = resolve_allowed_destinations(
        configured_destinations=settings.commissioning_only_destinations,
        cli_destinations=cli_only_destinations,
    )
    if not allowed_destinations:
        return controller_repository
    return FilteredControllerRepository(
        base=controller_repository,
        allowed_destinations=allowed_destinations,
    )


def resolve_allowed_destinations(
    *,
    configured_destinations: tuple[str, ...],
    cli_destinations: list[str],
) -> set[str]:
    configured = set(configured_destinations)
    cli = set(cli_destinations)
    if configured and cli:
        return configured & cli
    if configured:
        return configured
    return cli


if __name__ == "__main__":
    raise SystemExit(main())


def _print_explanations(snapshot) -> None:
    for item in snapshot.evaluation_results or []:
        explanation = item.explanation
        print(
            "explain "
            f"record_id={explanation.schedule_record_id} "
            f"matched={explanation.matched} "
            f"skip_reason={explanation.skip_reason} "
            f"output_type={explanation.output_type} "
            f"zone_category={explanation.zone_category} "
            f"output_index={explanation.output_index} "
            f"timer_ms={explanation.timer_ms} "
            f"groups={explanation.group_select} "
            f"controllers={explanation.controller_links} "
            f"irrigation_allowed={explanation.irrigation_allowed} "
            f"irrigation_reason={explanation.irrigation_reason}"
        )
