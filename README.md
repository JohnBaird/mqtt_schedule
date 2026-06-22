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
- A Linux-oriented service runner with minute-boundary scheduling and periodic jobs.
- Legacy-compatible MQTT publish support for:
  - `stc_airtable_output_onoff_request`
  - `stc_online_status_request`
  - `stc_input_status_request`
  - `stc_temperature_request`
  - `stc_online_status_response`
  - `stc_input_status_response`
  - `stc_access_response`
- Live inbound MQTT handling for:
  - `stc_access_request`
  - `stc_online_status_request`
  - `stc_input_status_request`
  - `stc_online_status_response`
  - `stc_input_status_response`
  - `stc_temperature_response`
  - `stc_config_file_response`
  - `stc_transaction_response`
- Legacy-compatible CSV reporting for:
  - `stc_access_request`
  - `stc_temperature_response`
  - `stc_transaction_response`
- File-backed OpenWeather/Tempest refresh jobs for Linux deployment.

Still intentionally incomplete:

- MongoDB ingestion/history responsibilities
- authoritative upstream producer for the Airtable JSON exports

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
- `docs/airtable-file-contract.md`
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
- The Airtable export file contract is documented in [airtable-file-contract.md](E:\Development\mqtt_schedule\docs\airtable-file-contract.md:1).

Planned placement for connection information:

- MQTT broker host/port and scheduling behavior: `runtime.json`
- MQTT username/password: `mqtt_schedule.env`
- Airtable base URL/base id/table names: `runtime.json`
- Airtable API key: `mqtt_schedule.env`
- OpenWeather API key: `mqtt_schedule.env`
- Tempest token: `mqtt_schedule.env`
- controller sysinfo snapshots: `clients_sysinfo_dir` in `runtime.json`
- CSV report paths and rotation settings: `runtime.json`
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
- The same service loop also publishes periodic controller status/temperature requests when enabled in config.
- `python -m mqtt_schedule --refresh-weather-now` forces the configured weather refresh jobs to run immediately and update the local files.
- `python -m mqtt_schedule --validate-airtable-files` validates the file-based Airtable contract and exits.
- `SIGINT` and `SIGTERM` trigger graceful shutdown.
- A sample `systemd` unit is included at [mqtt_schedule.service](E:\Development\mqtt_schedule\deploy\mqtt_schedule.service:1).

Current inbound MQTT behavior:

- `stc_access_request` is answered with `stc_access_response`.
- access decisions are logged with explicit reasons such as `granted`, `credential_not_found`, `group_mismatch`, or `access_user_data_unavailable`.
- `stc_access_request` also appends a legacy-style request-side row to `transactions.csv`.
- `stc_online_status_request` is answered with `stc_online_status_response`.
- `stc_input_status_request` is answered with `stc_input_status_response`.
- `stc_online_status_response` and `stc_input_status_response` are consumed and logged.
- `stc_online_status_response` also updates the file-backed controller state at `controller_status_file`.
- `stc_temperature_response` is consumed, logged, and appended to the legacy-style temperature CSV.
- `stc_config_file_response` is consumed and its `sysConfig` payload is written to `clients_sysinfo_dir`.
- `stc_transaction_response` is consumed, logged, and appended to the legacy-style transaction CSV.
- `stc_online_status_response` with `reason="restarted"` automatically triggers `stc_config_file_request` back to that controller.

Current Airtable sync behavior:

- `python -m mqtt_schedule --sync-airtable-now` fetches controller, schedule, and access-user exports from Airtable into the local JSON contract files.
- if `airtable_schedule_data.json`, `airtable_config_data.json`, or `airtable_access_users.json` is missing at startup, the service immediately attempts an Airtable sync before continuing.
- identical Airtable payloads do not overwrite the existing local files.

CSV reporting settings:

- `transaction_csv_file` defaults to `/var/lib/mqtt_schedule/transactions.csv`
- `temperature_csv_file` defaults to `/var/lib/mqtt_schedule/temperature.csv`
- `csv_backup_dir` defaults to `/var/lib/mqtt_schedule/csv_backup`
- `transaction_csv_max_entries` and `temperature_csv_max_entries` default to `5000`
- `transaction_csv_backup_count` and `temperature_csv_backup_count` default to `10`

Controller status settings:

- `controller_status_file` defaults to `/var/lib/mqtt_schedule/controller_status.json`
- each inbound `stc_online_status_response` updates that file with the controller's last seen timestamp, response, reason, and restart/config-sync markers

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
   Validate them first with:

```bash
/opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --validate-airtable-files
```

   Or fetch them directly from Airtable:

```bash
/opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --sync-airtable-now
```

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

If you want controller config snapshots saved from inbound `stc_config_file_response`, set this in `/etc/mqtt_schedule/runtime.json`:

```json
"clients_sysinfo_dir": "/etc/mqtt_schedule/clients_sysinfo"
```

Then create the directory and make it writable by the service user:

```bash
sudo mkdir -p /etc/mqtt_schedule/clients_sysinfo
sudo chown -R mqttschedule:mqttschedule /etc/mqtt_schedule/clients_sysinfo
```

## Linux Update Flow

For normal Linux updates, use `/opt/mqtt_schedule` as the one real checkout. Do not use a long-lived staging copy such as `~/mqtt_schedule_temp` for routine updates.

Recommended update flow:

```bash
cd /opt/mqtt_schedule
git pull
/opt/mqtt_schedule/.venv/bin/python -m pip install .
sudo systemctl restart mqtt_schedule
sudo journalctl -u mqtt_schedule -n 50 --no-pager
```

Operational note:

- `mqtt_schedule` logs to the `systemd` journal, not to a plain text logfile.
- Use `journalctl -u mqtt_schedule` and pipe to `grep` if needed.

Examples:

```bash
sudo journalctl -u mqtt_schedule --since today | grep online_status_response
sudo journalctl -u mqtt_schedule -n 200 | grep config_file_response
```

## Staging Venv Recovery

During Linux commissioning, the staging virtual environment at `/home/john/mqtt_schedule_temp/.venv` can become polluted with broken package leftovers if installs or uninstalls were previously run under mixed users such as `john` and `root`.

Symptoms:

- `pip install .` succeeds, but prints warnings such as:
  - `WARNING: Ignoring invalid distribution -`
  - `WARNING: Ignoring invalid distribution -qtt-schedule`
- The actual service under `/opt/mqtt_schedule/.venv` can still be healthy while only the staging venv is noisy.

Recommended clean install flow for the staging venv:

```bash
deactivate 2>/dev/null || true
rm -rf /home/john/mqtt_schedule_temp/.venv
python3 -m venv /home/john/mqtt_schedule_temp/.venv
source /home/john/mqtt_schedule_temp/.venv/bin/activate
/home/john/mqtt_schedule_temp/.venv/bin/python -m pip install --upgrade pip
/home/john/mqtt_schedule_temp/.venv/bin/python -m pip install /home/john/mqtt_schedule_temp
```

Important detail:

- Prefer `/home/john/mqtt_schedule_temp/.venv/bin/python -m pip ...` over plain `pip ...` so the command always targets the intended venv.

If the warnings still appear, inspect `site-packages` for junk directories:

```bash
find /home/john/mqtt_schedule_temp/.venv/lib/python3.10/site-packages -maxdepth 1 \( -name '-*' -o -name '~*' -o -name '*qtt_schedule*' \) -ls
```

If the output shows leftovers such as these:

- `~qtt_schedule`
- `~qtt_schedule-0.1.0.dist-info`
- `~-tt_schedule`
- `~-tt_schedule-0.1.0.dist-info`

remove them with `sudo` because they may be owned by `root`:

```bash
sudo rm -rf /home/john/mqtt_schedule_temp/.venv/lib/python3.10/site-packages/~qtt_schedule
sudo rm -rf /home/john/mqtt_schedule_temp/.venv/lib/python3.10/site-packages/~qtt_schedule-0.1.0.dist-info
sudo rm -rf /home/john/mqtt_schedule_temp/.venv/lib/python3.10/site-packages/~-tt_schedule
sudo rm -rf /home/john/mqtt_schedule_temp/.venv/lib/python3.10/site-packages/~-tt_schedule-0.1.0.dist-info
```

Verify the junk is gone:

```bash
find /home/john/mqtt_schedule_temp/.venv/lib/python3.10/site-packages -maxdepth 1 \( -name '-*' -o -name '~*' -o -name '*qtt_schedule*' \) -ls
```

If that final `find` prints nothing, reinstall once more:

```bash
/home/john/mqtt_schedule_temp/.venv/bin/python -m pip install /home/john/mqtt_schedule_temp
```

After the cleanup succeeds, the install should complete without the invalid-distribution warnings.

## Update History

Keep this section at the end of the README and update it whenever behavior changes in a meaningful way. The format should stay lightweight: short commit hash plus one-line summary.

Recent history from git:

- `7c3fd0f` Request config file after controller restart
- `dda9aa1` Add legacy CSV reporting for inbound responses
- `ebc1081` Handle inbound transaction responses
- `62b3e22` Update README for current Linux and MQTT behavior
- `94e6cd3` Handle config file responses
- `bbef50a` Handle inbound temperature responses
- `b7c146e` Handle inbound controller status responses
- `ba30883` Handle inbound input status requests
- `f6eaaa1` Handle inbound online status requests
- `1266cd5` Fail safe on missing access user data
- `866c548` Add inbound MQTT callback diagnostics
- `640c7eb` Add inbound MQTT access-request handler
- `8db6461` Log service startup through logger
- `1d544a6` Improve service shutdown behavior
- `44ff089` Harden Linux install permissions
- `4c4bc04` Enable live weather refresh commissioning
- `d2c3a21` Add service commissioning logs
- `c277ade` Add service-safe commissioning destination filter
- `b9adea0` Initial professional rewrite foundation
