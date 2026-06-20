# Legacy System Analysis

This document summarizes what `E:\Development\mqtt_schedule_old` currently does so we can rewrite it without losing behavior.

## High-Level Purpose

The legacy application is an automation service for irrigation controllers and nearby devices. It uses Airtable as an operator-managed source of truth for schedules and controller membership, MQTT as the control bus, and weather data to suppress irrigation when rainfall thresholds are met.

## Main Runtime Flow

The current entrypoint is [`main.py`](E:\Development\mqtt_schedule_old\main.py).

At startup it:

- Loads config from `config/config.json`.
- Loads secrets from `config/.credentials.json`.
- Creates a rotating logger and CSV writers.
- Loads Airtable snapshots for:
  - `irrigation-config`
  - `irrigation-schedule`
  - `irrigation-zone-desc`
  - `access-users`
- Creates an MQTT client and outbound queue processor.
- Creates OpenWeather and Tempest/WeatherFlow clients.
- Connects to MongoDB and creates query/ingestion helpers.
- Starts a timer loop.

The main loop then:

- Ticks the scheduler very frequently.
- Runs wall-clock tasks at minute, 5-minute, 20-minute, hourly, 3-hour, and daily boundaries.
- Services inbound MQTT messages from a queue.

## External Systems

The legacy app depends on:

- Airtable for configuration and schedule exports.
- MQTT broker for controller communication.
- MongoDB for weather history and ingestion metadata.
- OpenWeather for sunrise/sunset and forecast/current weather files.
- Tempest/WeatherFlow for station metadata and observations.

## Core Business Behavior

### 1. Airtable schedule evaluation

The main schedule logic lives in [`airtable_process.py`](E:\Development\mqtt_schedule_old\airtable_process.py).

Each schedule row is considered active only when:

- `enabled` is exactly `true`
- season matches current season or includes `All_seasons`
- day rule matches today
- time window matches the current local time

Supported time styles:

- normal wall-clock window using `start_time` and `end_time`
- cross-midnight windows
- sunrise-triggered windows
- sunset-triggered windows

Supported day rules:

- `Every_day`
- `Week_days_even`
- `Week_days_odd`
- explicit day names such as `Monday` or `Mon`

Relevant schedule fields observed in Airtable data:

- `enabled`
- `seasonNames`
- `day_of_week`
- `start_time`
- `end_time`
- `duration_on`
- `zoneNumber`
- `groupSelect`
- `zone_category`
- `output-type`

### 2. Controller targeting

The Airtable config file maps group membership to target controllers.

Observed controller fields:

- `enabled`
- `groupSelect`
- `Name`
- `nameLink`
- `ipAddress`

The scheduler builds a `nameLink -> serialNumber/nameLink` map for all matching controllers in the same group, then publishes the output command to each target.

### 3. Rain-based irrigation suppression

For `output-irrigation` schedules only, the app asks `HomeWeatherQueries.decide_irrigation(...)` whether irrigation should be allowed.

The weather policy uses Tempest rainfall data as the source of truth and applies thresholds from config:

- rain now block
- last 24h block
- last 48h block
- last 7d block
- freshness requirement for latest observation

If the decision denies irrigation, the schedule row is skipped and a log entry is written.

### 4. MQTT publishing

The MQTT topic shape is:

`SPV1.0/<domain>/<command>/<source_serial>/<destination_serial>`

Compatibility requirement:

- The outbound MQTT publish format is a fixed hardware protocol.
- Topic structure, command names, payload field names, and timestamp format must remain legacy-compatible.
- Internal refactors are allowed, but wire-format changes require deliberate compatibility planning and should be treated as breaking changes.

Important outbound commands found in the legacy app:

- `stc_airtable_output_onoff_request`
- `stc_online_status_request`
- `stc_online_status_response`
- `stc_input_status_request`
- `stc_input_status_response`
- `stc_temperature_request`
- `stc_temperature_response`
- `stc_sysinfo_request`
- `stc_config_file_request`
- `stc_access_response`

Observed payload contract for `stc_airtable_output_onoff_request`:

- `_iD`
- `clientId`
- `programVersion`
- `dateTime`
- `unixTime`
- `onOff`
- `timerValue`
- `outputIndex`
- `airtableOutputType`
- `airtableZoneCategory`
- `airtableGroups`

Important inbound commands handled by the queue processor:

- `ident/roc_access_request`
- `irrigation/stc_online_status_request`
- `irrigation/stc_online_status_response`
- `irrigation/stc_input_status_request`
- `irrigation/stc_input_status_response`
- `irrigation/stc_temperature_response`
- `irrigation/stc_access_request`
- `irrigation/stc_config_file_response`
- `irrigation/stc_transaction_response`

### 5. Periodic jobs

The timed tasks are:

- every minute
  - evaluate schedule
  - request MQTT online/input status
  - optionally publish server online status
- every 20 minutes
  - request controller temperatures
  - publish local CPU temperature
  - append temperature CSV
- every hour
  - refresh Tempest files
  - ingest Tempest station metadata and observations into MongoDB
- every 3 hours
  - refresh Airtable user/schedule exports
  - fetch OpenWeather current/forecast
  - ingest OpenWeather data into MongoDB
- daily
  - run retention/debug-style reporting against historical weather data

## Legacy Design Problems

The current code works as a prototype, but it is hard to maintain because:

- one startup path creates nearly every service directly
- integration code and business rules are mixed together
- modules rely on mutable shared objects instead of explicit contracts
- many methods read files directly instead of using repositories
- inbound and outbound MQTT protocol handling is spread across multiple classes
- configuration is loosely typed
- testing the schedule logic requires understanding many unrelated modules
- there are duplicate or superseded methods still present in files
- some names no longer match responsibility, which increases onboarding cost

## Rewrite Direction

The rewrite should separate the system into these layers:

### Domain

- schedule models
- controller models
- weather policy input/output
- pure scheduling decisions

### Application services

- evaluate current schedule state
- refresh Airtable snapshots
- ingest weather data
- coordinate timer jobs

### Adapters

- Airtable client/repository
- MQTT publisher/subscriber
- MongoDB repositories
- OpenWeather client
- Tempest client
- file-based logging/export

## Recommended Migration Strategy

1. Freeze legacy behavior in docs and tests.
2. Rebuild the schedule engine as pure functions and typed models.
3. Add adapter interfaces and fake implementations.
4. Port MQTT publishing next because it is the core actuator path.
5. Port weather policy and repositories after the core scheduler is stable.
6. Add the runtime loop last, after the business rules are independently testable.
