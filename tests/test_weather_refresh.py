import json
import logging
from pathlib import Path

from mqtt_schedule.weather_refresh import TempestRefreshSettings, TempestRefresher, _snapshot_name


def test_snapshot_name_uses_yyyymmdd() -> None:
    from datetime import datetime, timezone

    name = _snapshot_name("station_meta.json", datetime(2026, 6, 20, tzinfo=timezone.utc))
    assert name == "station_meta_20260620.json"


def test_tempest_refresher_writes_current_and_snapshot(tmp_path: Path) -> None:
    class FakeTempestRefresher(TempestRefresher):
        def __init__(self, settings: TempestRefreshSettings) -> None:
            super().__init__(settings)

        def _get_json(self, url: str) -> dict:
            if "/stations?" in url:
                return {
                    "stations": [
                        {
                            "station_id": 201749,
                            "devices": [{"device_id": 468383, "device_type": "ST"}],
                        }
                    ]
                }
            if "/observations/station/" in url:
                return {"station_id": 201749, "obs": [{"timestamp": 1781963992}]}
            if "/observations/device/" in url:
                return {"device_id": 468383, "obs": [{"timestamp": 1781963992}]}
            raise AssertionError(url)

    refresher = FakeTempestRefresher(
        TempestRefreshSettings(
            base_url="https://example.test",
            token="secret",
            data_dir=tmp_path,
            snapshot_keep=5,
        )
    )

    refresher.refresh()

    assert (tmp_path / "station_meta.json").exists()
    assert any(path.name.startswith("station_meta_") for path in tmp_path.iterdir())
    assert (tmp_path / "station_obs_201749.json").exists()
    assert (tmp_path / "device_obs_468383.json").exists()
    assert json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))["epoch"] > 0


def test_tempest_refresher_logs_refresh(caplog, tmp_path: Path) -> None:
    class FakeTempestRefresher(TempestRefresher):
        def _get_json(self, url: str) -> dict:
            if "/stations?" in url:
                return {"stations": []}
            raise AssertionError(url)

    caplog.set_level(logging.INFO)
    refresher = FakeTempestRefresher(
        TempestRefreshSettings(
            base_url="https://example.test",
            token="secret",
            data_dir=tmp_path,
            snapshot_keep=5,
        )
    )

    refresher.refresh()

    messages = [record.getMessage() for record in caplog.records]
    assert any("tempest_refresh_start" in message for message in messages)
    assert any("tempest_refresh_complete" in message for message in messages)
