from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .airtable_repositories import FileControllerRepository, FileScheduleRepository
from .app import SchedulerApplication
from .hostinfo import HostInfoProvider
from .identity import DeviceIdentity, DeviceIdentitySettings
from .mqtt_adapter import MQTTBrokerSettings, MQTTCommandEncoder, PahoClientFactory, PahoCommandPublisher
from .scheduler import ScheduleEvaluator, SchedulerConfig
from .settings import RuntimeSettings
from .weather_adapters import OpenWeatherFileSunTimesProvider, TempestFileRainPolicy


def build_file_backed_application(settings: RuntimeSettings) -> SchedulerApplication:
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

    mqtt_settings = MQTTBrokerSettings(
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
    client = PahoClientFactory.connect(mqtt_settings)
    publisher = PahoCommandPublisher(client=client, encoder=MQTTCommandEncoder(mqtt_settings))

    return SchedulerApplication(
        schedule_repository=FileScheduleRepository(settings.schedule_file),
        controller_repository=FileControllerRepository(settings.controller_file),
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
