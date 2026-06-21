# mqtt_schedule

Maintainable rewrite of the legacy `mqtt_schedule_old` service.

## Goals

- Preserve the useful behavior of the legacy system.
- Replace tightly-coupled scripts with typed, testable modules.
- Make scheduling, irrigation policy, and MQTT publishing understandable in isolation.
- Keep external integrations behind small interfaces so they can be mocked and tested.

## Legacy Responsibilities

The previous program was doing all of these jobs in one process:

- Load local JSON configuration and credentials.
- Pull configuration and schedule data from Airtable.
- Poll OpenWeather and Tempest/WeatherFlow.
- Ingest weather data into MongoDB.
- Evaluate schedule rows every minute.
- Suppress irrigation when recent rain exceeds thresholds.
- Publish MQTT commands to irrigation controllers.
- Process inbound MQTT status/access messages.
- Record temperature and transaction CSV logs.

## Rewrite Status

This repository currently contains:

- A reverse-engineering summary of the legacy application.
- A typed domain model for schedule evaluation.
- A pure scheduler engine that can be tested without MQTT, Airtable, or MongoDB.
- A small application service skeleton showing how adapters should plug in.

## Local Python Runtime

This repo now includes a project-local Python runtime at:

- `E:\Development\mqtt_schedule\.tools\python\runtime\python.exe`

Useful commands:

```powershell
& 'E:\Development\mqtt_schedule\.tools\python\runtime\python.exe' --version
& 'E:\Development\mqtt_schedule\.tools\python\runtime\python.exe' -m pytest -q
& 'E:\Development\mqtt_schedule\.tools\python\runtime\python.exe' -m mqtt_schedule --dry-run
& 'E:\Development\mqtt_schedule\.tools\python\runtime\python.exe' -m mqtt_schedule --service
```

## Project Layout

- `docs/legacy-system-analysis.md`
- `src/mqtt_schedule/domain.py`
- `src/mqtt_schedule/scheduler.py`
- `src/mqtt_schedule/app.py`
- `tests/test_scheduler.py`

## Next Steps

1. Implement Airtable, MQTT, weather, and persistence adapters.
2. Add config loading and secrets handling.
3. Add a real runner with wall-clock timers.
4. Migrate one integration at a time behind tests.

## Linux Notes

This service is intended to run on Linux.

- `RuntimeSettings.from_env()` defaults to `/etc/mqtt_schedule` for exported Airtable JSON files.
- Weather defaults expect:
  - `/etc/mqtt_schedule/ow_records_current.json`
  - `/etc/mqtt_schedule/tempest_weather_data/`
- The new code uses `pathlib.Path` and environment-based configuration rather than Windows-only paths.
- We can add a `systemd` service file and deployment layout once the first end-to-end runtime path is in place.

Configuration layout:

- Non-secret operational settings belong in `/etc/mqtt_schedule/runtime.json`.
- Secrets and connection credentials belong in `/etc/mqtt_schedule/mqtt_schedule.env`.
- When `--config /etc/mqtt_schedule/runtime.json` is used, environment variables from `mqtt_schedule.env` still override JSON values for secrets and commissioning-time overrides.
- The sample files are:
  - [runtime.example.json](E:\Development\mqtt_schedule\deploy\runtime.example.json:1)
  - [mqtt_schedule.env.example](E:\Development\mqtt_schedule\deploy\mqtt_schedule.env.example:1)

Planned placement for connection information:

- MQTT broker host/port and scheduling behavior: `runtime.json`
- MQTT username/password: `mqtt_schedule.env`
- OpenWeather API key: `mqtt_schedule.env`
- Tempest token: `mqtt_schedule.env`
- Persisted device identity: `/var/lib/mqtt_schedule/device_serial.txt`
- Temporary commissioning destination filter: `runtime.json` or `mqtt_schedule.env`

This split is intentional so we do not keep secrets in the main checked-in config file.
The MQTT topic source serial is derived from machine identity and persisted as runtime state, not edited as normal config.

Commissioning safety:

- `commissioning_only_destinations` in `runtime.json` limits all runs, including `--service`, to specific controller serials.
- `MQTT_SCHEDULE_ONLY_DESTINATIONS` in `mqtt_schedule.env` provides the same filter as a comma-separated list.
- CLI `--only-destination` can further narrow the configured filter, but it cannot widen it.

Service runtime:

- `python -m mqtt_schedule --service` runs the scheduler continuously.
- The service loop fires once per minute on the wall-clock minute boundary.
- The same service loop can also refresh OpenWeather and Tempest files on independent intervals when credentials are configured.
- `python -m mqtt_schedule --refresh-weather-now` forces the configured weather refresh jobs to run immediately and update the local files.
- `SIGINT` and `SIGTERM` trigger graceful shutdown.
- A sample `systemd` unit is included at [mqtt_schedule.service](E:\Development\mqtt_schedule\deploy\mqtt_schedule.service:1).

## MQTT Compatibility

The MQTT publish format is a hardware compatibility contract.

- Do not rename payload fields.
- Do not change topic structure.
- Do not change `dateTime` formatting without a compatibility plan.
- Treat outbound publish changes as breaking protocol changes.

## First Tests

For the first Linux-style tests, the intended flow is:

1. Upload the repo to a normal user-writable staging path such as `/home/john/mqtt_schedule_temp`.
2. Run the install script as `root`:

```bash
sudo bash /home/john/mqtt_schedule_temp/deploy/install_linux.sh /home/john/mqtt_schedule_temp
```

The installer intentionally:

- excludes staging-only directories such as `.venv` and `.pytest_cache`
- creates a fresh `/opt/mqtt_schedule/.venv`
- prepares writable weather output paths for the `mqttschedule` service user
- keeps `runtime.json` root-owned while allowing the service to write weather refresh temp files under `/etc/mqtt_schedule`

3. Edit `/etc/mqtt_schedule/runtime.json`.
4. Edit `/etc/mqtt_schedule/mqtt_schedule.env`.
5. Place or sync the Airtable export files into `/etc/mqtt_schedule/`.
6. Run a safe dry-run first:

```bash
/opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --dry-run
```

7. Then run the service mode:

```bash
/opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --service
```

For commissioning one real controller in service mode, set either:

```json
"commissioning_only_destinations": ["242606363309393"]
```

or:

```bash
MQTT_SCHEDULE_ONLY_DESTINATIONS=242606363309393
```

For live weather commissioning:

- Put `MQTT_SCHEDULE_OPENWEATHER_API_KEY` and `MQTT_SCHEDULE_TEMPEST_TOKEN` in `/etc/mqtt_schedule/mqtt_schedule.env`.
- Temporarily shorten `weather_refresh_openweather_seconds` and `weather_refresh_tempest_seconds` in `runtime.json` if you want faster repeated refresh testing.
- Set `weather_refresh_run_immediately` in `runtime.json` or `MQTT_SCHEDULE_WEATHER_REFRESH_RUN_IMMEDIATELY=true` in the env file if you want refresh jobs to fire as soon as the service starts.
- For a one-time manual refresh without waiting for service intervals, run:

```bash
/opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --refresh-weather-now --dry-run
```
