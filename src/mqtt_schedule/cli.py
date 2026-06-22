from __future__ import annotations

import argparse
import json
from datetime import datetime
import logging
from pathlib import Path

from .airtable_repositories import (
    FileControllerRepository,
    FileScheduleRepository,
    validate_access_users_file,
    validate_controller_file,
    validate_schedule_file,
)
from .access_control import AccessDecisionService, FileAccessUserRepository
from .app import ControllerRepository, FilteredControllerRepository, SchedulerApplication
from .airtable_sync import AirtableSyncService
from .controller_status import ControllerStatusStore
from .csv_reporting import LegacyCsvRecorder
from .hostinfo import HostInfoProvider
from .identity import DeviceIdentity, DeviceIdentitySettings
from .mongo import MongoDatabase
from .mongo_ingestion import MongoIngestionRunRepository
from .mongo_openweather import OpenWeatherMongoIngestService
from .mongo_tempest import TempestMongoIngestService
from .inbound import AccessRequestMessageHandler
from .mqtt_adapter import AccessResponseRequestContext, MQTTBrokerSettings, MQTTCommandEncoder, PahoClientFactory, PahoCommandPublisher, StdoutCommandPublisher
from .mqtt_adapter import MQTTMaintenancePublisher
from .mqtt_adapter import SPTopic
from .scheduler import ScheduleEvaluator, SchedulerConfig
from .service import PeriodicJob, ServiceConfig, ServiceRunner, SignalAwareService, seconds_until_next_minute
from .settings import RuntimeSettings
from .weather_adapters import OpenWeatherFileSunTimesProvider, TempestFileRainPolicy
from .weather_refresh import OpenWeatherRefreshSettings, OpenWeatherRefresher, TempestRefreshSettings, TempestRefresher
from .domain import AccessRequest


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
        "--validate-airtable-files",
        action="store_true",
        help="Validate the file-based Airtable export contract and exit.",
    )
    parser.add_argument(
        "--sync-airtable-now",
        action="store_true",
        help="Fetch Airtable exports now and update local contract files before exiting.",
    )
    parser.add_argument("--handle-access-request-topic", help="Process one legacy stc_access_request topic and exit.")
    parser.add_argument("--handle-access-request-payload", help="Process one legacy stc_access_request payload JSON and exit.")
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
    if args.sync_airtable_now:
        return _sync_airtable_now(settings)
    _ensure_required_airtable_files(settings)
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

    access_request_handler = None
    controller_status_store = None
    subscriptions: list[str] = []

    if args.dry_run:
        publisher = StdoutCommandPublisher(encoder)
        client = None
    else:
        csv_recorder = LegacyCsvRecorder.from_settings(settings)
        controller_status_store = ControllerStatusStore(
            settings.controller_status_file,
            csv_recorder=csv_recorder,
        )
        access_request_handler = AccessRequestMessageHandler(
            settings=settings,
            maintenance_publisher=MQTTMaintenancePublisher(encoder=encoder, client=None),
            source_serial=source_serial,
            csv_recorder=csv_recorder,
            controller_status_store=controller_status_store,
        )
        subscriptions.extend(access_request_handler.subscription_topics())
        for topic in access_request_handler.subscription_topics():
            logging.getLogger("mqtt_schedule.cli").info(
                "inbound_subscription_configured topic=%s",
                topic,
            )
        client = PahoClientFactory.connect(
            encoder.settings,
            subscriptions=subscriptions,
            on_message=access_request_handler.handle_message,
        )
        publisher = PahoCommandPublisher(client=client, encoder=encoder)
    maintenance_publisher = MQTTMaintenancePublisher(encoder=encoder, client=client)
    if access_request_handler is not None:
        access_request_handler.maintenance_publisher = maintenance_publisher

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

    if args.validate_airtable_files:
        return _validate_airtable_files(settings)

    if args.handle_access_request_topic or args.handle_access_request_payload:
        if not args.handle_access_request_topic or not args.handle_access_request_payload:
            raise SystemExit("--handle-access-request-topic and --handle-access-request-payload must be used together.")
        return _handle_access_request(
            settings=settings,
            maintenance_publisher=maintenance_publisher,
            topic=args.handle_access_request_topic,
            payload_json=args.handle_access_request_payload,
        )

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
        airtable_sync_jobs = build_airtable_sync_jobs(
            settings=settings,
        )
        openweather_mongo_ingest_jobs = build_openweather_mongo_ingest_jobs(
            settings=settings,
        )
        tempest_mongo_ingest_jobs = build_tempest_mongo_ingest_jobs(
            settings=settings,
        )
        mqtt_request_jobs = build_mqtt_request_jobs(
            settings=settings,
            controller_repository=controller_repository,
            maintenance_publisher=maintenance_publisher,
        )
        controller_status_jobs = build_controller_status_jobs(
            settings=settings,
            controller_status_store=controller_status_store,
        )
        if args.service:
            if args.refresh_weather_now:
                _run_weather_refresh_now(refresh_jobs)
            runner = ServiceRunner(
                app,
                config=ServiceConfig(run_immediately=args.run_immediately),
                periodic_jobs=refresh_jobs + airtable_sync_jobs + openweather_mongo_ingest_jobs + tempest_mongo_ingest_jobs + mqtt_request_jobs + controller_status_jobs,
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


def build_airtable_sync_jobs(
    *,
    settings: RuntimeSettings,
) -> list[PeriodicJob]:
    logger = logging.getLogger("mqtt_schedule.cli")
    sync_service = AirtableSyncService(settings)
    if not sync_service.is_configured():
        logger.info("airtable_sync_disabled reason=missing_configuration")
        return []
    if settings.airtable_sync_seconds <= 0:
        logger.info(
            "airtable_sync_disabled reason=non_positive_interval interval_seconds=%s",
            settings.airtable_sync_seconds,
        )
        return []

    def sync_airtable() -> None:
        sync_service.sync_all()

    logger.info(
        "airtable_sync_configured interval_seconds=%s run_immediately=%s",
        settings.airtable_sync_seconds,
        settings.airtable_sync_run_immediately,
    )
    return [
        PeriodicJob(
            job_id="airtable-sync",
            interval_seconds=settings.airtable_sync_seconds,
            fn=sync_airtable,
            run_immediately=settings.airtable_sync_run_immediately,
        )
    ]


def build_tempest_mongo_ingest_jobs(
    *,
    settings: RuntimeSettings,
) -> list[PeriodicJob]:
    logger = logging.getLogger("mqtt_schedule.cli")
    if not settings.mongo_uri or not settings.mongo_db:
        logger.info("tempest_mongo_ingest_disabled reason=missing_mongo_configuration")
        return []
    if settings.mongo_tempest_ingest_seconds <= 0:
        logger.info(
            "tempest_mongo_ingest_disabled reason=non_positive_interval interval_seconds=%s",
            settings.mongo_tempest_ingest_seconds,
        )
        return []

    def ingest_tempest() -> None:
        database = MongoDatabase(settings)
        try:
            database.ensure_indexes()
            collections = database.collections()
            service = TempestMongoIngestService(
                stations_collection=collections.stations,
                tempest_flow_collection=collections.tempest_flow,
                ingestion_runs=MongoIngestionRunRepository(collections.ingestion_runs),
            )
            service.ingest_directory(settings.tempest_data_dir)
        finally:
            database.close()

    logger.info(
        "tempest_mongo_ingest_configured interval_seconds=%s run_immediately=%s",
        settings.mongo_tempest_ingest_seconds,
        settings.mongo_tempest_ingest_run_immediately,
    )
    return [
        PeriodicJob(
            job_id="tempest-mongo-ingest",
            interval_seconds=settings.mongo_tempest_ingest_seconds,
            fn=ingest_tempest,
            run_immediately=settings.mongo_tempest_ingest_run_immediately,
        )
    ]


def build_openweather_mongo_ingest_jobs(
    *,
    settings: RuntimeSettings,
) -> list[PeriodicJob]:
    logger = logging.getLogger("mqtt_schedule.cli")
    if not settings.mongo_uri or not settings.mongo_db:
        logger.info("openweather_mongo_ingest_disabled reason=missing_mongo_configuration")
        return []
    if settings.mongo_openweather_ingest_seconds <= 0:
        logger.info(
            "openweather_mongo_ingest_disabled reason=non_positive_interval interval_seconds=%s",
            settings.mongo_openweather_ingest_seconds,
        )
        return []

    def ingest_openweather() -> None:
        database = MongoDatabase(settings)
        try:
            database.ensure_indexes()
            collections = database.collections()
            service = OpenWeatherMongoIngestService(
                open_weather_collection=collections.open_weather,
                ingestion_runs=MongoIngestionRunRepository(collections.ingestion_runs),
            )
            service.ingest_files(
                current_file=settings.openweather_current_file,
                forecast_file=settings.openweather_forecast_file,
            )
        finally:
            database.close()

    logger.info(
        "openweather_mongo_ingest_configured interval_seconds=%s run_immediately=%s",
        settings.mongo_openweather_ingest_seconds,
        settings.mongo_openweather_ingest_run_immediately,
    )
    return [
        PeriodicJob(
            job_id="openweather-mongo-ingest",
            interval_seconds=settings.mongo_openweather_ingest_seconds,
            fn=ingest_openweather,
            run_immediately=settings.mongo_openweather_ingest_run_immediately,
        )
    ]


def _run_weather_refresh_now(jobs: list[PeriodicJob]) -> None:
    logger = logging.getLogger("mqtt_schedule.cli")
    if not jobs:
        logger.info("weather_refresh_now_skipped reason=no_configured_jobs")
        return
    logger.info("weather_refresh_now_start job_count=%s", len(jobs))
    for job in jobs:
        job.fn()
    logger.info("weather_refresh_now_complete job_count=%s", len(jobs))


def _validate_airtable_files(settings: RuntimeSettings) -> int:
    schedule_summary = validate_schedule_file(settings.schedule_file)
    controller_summary = validate_controller_file(settings.controller_file)
    access_users_summary = validate_access_users_file(settings.access_users_file)
    summaries = [schedule_summary, controller_summary, access_users_summary]

    for summary in summaries:
        print(
            "airtable_file "
            f"kind={summary.file_kind} "
            f"path={summary.path} "
            f"record_count={summary.record_count} "
            f"valid_count={summary.valid_count} "
            f"ok={summary.ok}"
        )
        for issue in summary.issues:
            print(
                "airtable_issue "
                f"kind={summary.file_kind} "
                f"severity={issue.severity} "
                f"message={issue.message}"
            )

    return 0 if all(summary.ok for summary in summaries) else 1


def _sync_airtable_now(settings: RuntimeSettings) -> int:
    results = AirtableSyncService(settings).sync_all()
    for result in results:
        print(
            "airtable_sync "
            f"kind={result.file_kind} "
            f"table={result.table_name} "
            f"path={result.output_path} "
            f"record_count={result.record_count} "
            f"action={result.action}"
        )
    return 0


def _handle_access_request(
    *,
    settings: RuntimeSettings,
    maintenance_publisher: MQTTMaintenancePublisher,
    topic: str,
    payload_json: str,
) -> int:
    parsed_topic = SPTopic.parse(topic)
    if parsed_topic is None:
        print("access_request_error reason=invalid_topic")
        return 1
    if parsed_topic.command != "stc_access_request":
        print("access_request_error reason=unsupported_command")
        return 1

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        print(f"access_request_error reason=invalid_payload_json detail={exc}")
        return 1

    request = AccessRequest(
        source_serial=parsed_topic.source_serial,
        destination_serial=parsed_topic.destination_serial,
        pin_code=_payload_str_or_none(payload.get("pinCode")),
        pin_number=_payload_str_or_none(payload.get("pinNumber")),
        card_number=_payload_str_or_none(payload.get("cardNumber")),
        face_id=_payload_str_or_none(payload.get("faceId")),
    )

    decision = AccessDecisionService(
        repository=FileAccessUserRepository(settings.access_users_file),
        access_groups=list(settings.access_groups),
    ).decide(request)

    maintenance_publisher.publish_access_response_for_request(
        AccessResponseRequestContext(
            source_serial=request.source_serial,
            pin_code=request.pin_code,
            pin_number=request.pin_number,
            card_number=request.card_number,
            face_id=request.face_id,
            request_id=_payload_str_or_none(payload.get("_iD")),
        ),
        decision,
    )
    print(
        "access_request_result "
        f"source_serial={request.source_serial} "
        f"destination_serial={request.destination_serial} "
        f"granted={decision.granted} "
        f"full_name={decision.full_name} "
        f"matched_group={decision.matched_group} "
        f"matched_credential={decision.matched_credential}"
    )
    return 0


def build_mqtt_request_jobs(
    *,
    settings: RuntimeSettings,
    controller_repository: ControllerRepository,
    maintenance_publisher: MQTTMaintenancePublisher,
) -> list[PeriodicJob]:
    logger = logging.getLogger("mqtt_schedule.cli")
    jobs: list[PeriodicJob] = []

    def active_destinations() -> list[str]:
        return [
            controller.name_link
            for controller in controller_repository.list_controllers()
            if controller.enabled and controller.name_link
        ]

    def publish_online_status_request() -> None:
        maintenance_publisher.publish_online_status_request(active_destinations())

    def publish_input_status_request() -> None:
        maintenance_publisher.publish_input_status_request(active_destinations())

    def publish_temperature_request() -> None:
        maintenance_publisher.publish_temperature_request(active_destinations())

    mqtt_jobs = [
        (
            settings.mqtt_online_status_request_enabled,
            "mqtt-online-status-request",
            settings.mqtt_online_status_request_seconds,
            publish_online_status_request,
        ),
        (
            settings.mqtt_input_status_request_enabled,
            "mqtt-input-status-request",
            settings.mqtt_input_status_request_seconds,
            publish_input_status_request,
        ),
        (
            settings.mqtt_temperature_request_enabled,
            "mqtt-temperature-request",
            settings.mqtt_temperature_request_seconds,
            publish_temperature_request,
        ),
    ]

    for enabled, job_id, interval_seconds, fn in mqtt_jobs:
        if not enabled:
            logger.info("mqtt_request_disabled job_id=%s", job_id)
            continue
        jobs.append(
            PeriodicJob(
                job_id=job_id,
                interval_seconds=interval_seconds,
                fn=fn,
                run_immediately=False,
            )
        )
        logger.info(
            "mqtt_request_configured job_id=%s interval_seconds=%s",
            job_id,
            interval_seconds,
        )

    return jobs


def build_controller_status_jobs(
    *,
    settings: RuntimeSettings,
    controller_status_store: ControllerStatusStore | None,
) -> list[PeriodicJob]:
    logger = logging.getLogger("mqtt_schedule.cli")
    if controller_status_store is None:
        logger.info("controller_status_refresh_disabled reason=no_persistent_store")
        return []

    def refresh_controller_status() -> None:
        controller_status_store.refresh_online_flags(
            now=datetime.now(),
            offline_after_seconds=settings.controller_offline_after_seconds,
            online_recovery_after_seconds=settings.controller_online_recovery_after_seconds,
        )

    logger.info(
        "controller_status_refresh_configured interval_seconds=%s offline_after_seconds=%s online_recovery_after_seconds=%s",
        60,
        settings.controller_offline_after_seconds,
        settings.controller_online_recovery_after_seconds,
    )
    return [
        PeriodicJob(
            job_id="controller-status-refresh",
            interval_seconds=60,
            fn=refresh_controller_status,
            run_immediately=False,
        )
    ]


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


def _payload_str_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _ensure_required_airtable_files(settings: RuntimeSettings) -> None:
    logger = logging.getLogger("mqtt_schedule.cli")
    sync_service = AirtableSyncService(settings)
    missing_paths = sync_service.required_files_missing()
    if not missing_paths:
        return
    if not sync_service.is_configured():
        missing_text = ",".join(str(path) for path in missing_paths)
        raise RuntimeError(
            f"Required Airtable files are missing and Airtable sync is not configured: {missing_text}"
        )
    logger.info(
        "airtable_sync_startup_fetch missing_count=%s missing_paths=%s",
        len(missing_paths),
        ",".join(str(path) for path in missing_paths),
    )
    sync_service.sync_all()
    still_missing = [path for path in _required_airtable_files(settings) if not path.exists()]
    if still_missing:
        raise RuntimeError(
            f"Airtable sync completed but required files are still missing: {','.join(str(path) for path in still_missing)}"
        )


def _required_airtable_files(settings: RuntimeSettings) -> list[Path]:
    return [
        settings.schedule_file,
        settings.controller_file,
        settings.access_users_file,
    ]


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
