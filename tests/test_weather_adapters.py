from datetime import datetime
from pathlib import Path

from mqtt_schedule.weather_adapters import OpenWeatherFileSunTimesProvider, TempestFileRainPolicy


TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
LEGACY_CONFIG_DIR = REPO_ROOT / "tests" / "fixtures" / "legacy_config"
LEGACY_TEMPEST_DIR = REPO_ROOT / "tests" / "fixtures" / "legacy_tempest_weather_data"


def test_openweather_sun_times_are_converted_to_local_seconds() -> None:
    provider = OpenWeatherFileSunTimesProvider(
        LEGACY_CONFIG_DIR / "ow_records_current.json",
        timezone_name="America/New_York",
    )

    sun_times = provider.get_sun_times(datetime(2026, 6, 20, 12, 0, 0))

    assert 4 * 3600 <= sun_times.sunrise_seconds <= 8 * 3600
    assert 19 * 3600 <= sun_times.sunset_seconds <= 22 * 3600


def test_tempest_policy_blocks_irrigation_when_recent_rain_is_high() -> None:
    policy = TempestFileRainPolicy(
        LEGACY_TEMPEST_DIR,
        station_id=201749,
        rain_now_block_mm=2.0,
        rain_24h_block_mm=5.0,
        rain_48h_block_mm=8.0,
        rain_7d_block_mm=15.0,
        require_latest_within_minutes=180,
    )

    decision = policy.decide(datetime(2026, 6, 20, 12, 0, 0))

    assert decision.allow is False
    assert decision.reason in {"RAIN_24H_ENOUGH", "RAIN_48H_ENOUGH", "RAIN_7D_ENOUGH"}
    assert decision.metrics["rain_mm"]["last_24h"] >= 5.0
