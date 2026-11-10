## Airtable File Contract

The current `mqtt_schedule` rewrite treats Airtable exports as a file-based upstream contract.

This means the scheduler runtime does not treat Airtable as its day-to-day source of truth. Instead, a separate sync step produces local JSON files that the scheduler consumes.

- `/etc/mqtt_schedule/airtable_schedule_data.json`
- `/etc/mqtt_schedule/airtable_config_data.json`
- `/etc/mqtt_schedule/airtable_access_users.json`
- `/etc/mqtt_schedule/airtable_input_alerts.json` (optional; see the [input-alerts plan and contract](input-alerts-plan.md))

The scheduler service consumes those files as its source of truth. At startup it saves validated copies under `/var/lib/mqtt_schedule/airtable_backup/` (or `airtable_backup_dir` from `runtime.json`). If a live export is missing, startup restores it from the private backup when Airtable sync is disabled or a fetch fails. A successful sync refreshes the backup. The backup includes access-user credentials and stays on the server with private permissions.

The synthetic `deploy/examples/*.example.json` files document the export shapes. They are disabled examples and are never loaded as production configuration.

### Why This Contract Exists

This keeps the scheduler service focused on:

- evaluating schedules
- applying irrigation/weather policy
- publishing MQTT commands
- running the Linux service loop

It also lets us replace the legacy system incrementally instead of mixing Airtable API concerns into the already-working runtime path.

### Current Sync Behavior

The optional fourth export is fetched explicitly with `--sync-input-alerts-now`, or periodically when `airtable_input_alerts_sync_enabled` is true. Its manual command validates before replacing the file and exits before any MQTT/SMS/email setup. `--validate-input-alerts` validates the local export only. The three original files remain the required startup exports; adding optional alert rules does not enable input-edge notifications.

Live input-alert execution separately requires `input_alerts_enabled` in `runtime.json`. Requested and unsolicited responses share the same processor; it matches local controller/category/input/trigger rules and queues notifications only through enabled channels. Missing edge entries generate structured warnings, while explicitly disabled entries suppress sends without a missing-rule warning. Unconfigured levels do not generate warnings on every polling report. See the input-alert plan for timestamp, duplicate-state, and commissioning safeguards.

The current rule fields are `triggerSource` (`positiveEdge`, `negativeEdge`, `levelHigh`, `levelLow`), `notificationCooldown`, `startTime`, and `endTime`. Input indexes accept canonical single-digit text as well as numeric values from 0 through 7. Durations are exported as numeric whole seconds. All trigger types use time windows and per-rule/channel notification cooldowns; 0/0 means all day, and a zero cooldown means no rate limit beyond duplicate-report suppression. Cooldowns exist only in application memory and reset on restart. Legacy `edge` and `cycleTime` aliases remain supported with conflict validation, so existing cached rules/backups are still usable. Install the new code before fetching the new export; no runtime key changes are required.

The rewrite now includes a separate Airtable sync path:

- manual sync:

```bash
/opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --sync-airtable-now
```

- startup safety:
  if any required export is missing and `airtable_sync_seconds` is positive, startup fetches only the missing export when configured and then restores still-missing files from validated local backups
- optional startup refresh:
  three independent `airtable_*_sync_run_immediately` flags choose whether controller, schedule, or access-user exports are fetched when the service starts; all default to `false`
- disabled automatic sync:
  `"airtable_sync_seconds": 0` disables periodic and startup API calls, regardless of the three startup flags; existing files or validated backups are required. The explicit `--sync-airtable-now` command still fetches exports.

- no-op overwrite protection:
  if the fetched Airtable payload is identical to the current local JSON file, the file is left untouched instead of being rewritten

### Required Top-Level Shape

Each export must be a JSON object with a top-level `records` array:

```json
{
  "records": [
    {
      "id": "recExample",
      "fields": {
      }
    }
  ]
}
```

Each record should contain:

- `id`: Airtable record id string
- `fields`: object containing the Airtable field values used by the scheduler

All four table readers use the existing lowercase `enabled` convention: boolean `true` or legacy text `"true"` enables a row; false, missing, or other values disable it. Text comparison is case-insensitive and ignores surrounding whitespace. New tables should use checkboxes. An input-alert reference export is included as `deploy/examples/airtable_input_alerts.example.json`, disabled like the other synthetic examples.

### Schedule Export Contract

Expected file:

- `/etc/mqtt_schedule/airtable_schedule_data.json`

Fields used by the scheduler:

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

Important notes:

- `zoneNumber` is required for a record to become a usable schedule entry.
- `output-type` is read as a list and the first value is used.
- `zone_category` defaults to `Unknown` if missing.

Minimal valid example:

```json
{
  "records": [
    {
      "id": "rec16Vlj0tnqsGfbr",
      "fields": {
        "duration_on": 1800,
        "output-type": ["output-irrigation"],
        "enabled": true,
        "seasonNames": ["All_seasons"],
        "end_time": 43200,
        "day_of_week": ["Every_day"],
        "zoneNumber": ["Zone-8"],
        "start_time": 41400,
        "groupSelect": ["Group-A"],
        "zone_category": "Irrigation"
      }
    }
  ]
}
```

### Controller Export Contract

Expected file:

- `/etc/mqtt_schedule/airtable_config_data.json`

Fields used by the scheduler:

- `Name`
- `nameLink`
- `enabled`
- `groupSelect`
- `ipAddress`

Important notes:

- both `Name` and `nameLink` are required for a record to become a usable controller target
- `nameLink` is the destination serial used in MQTT topics

Minimal valid example:

```json
{
  "records": [
    {
      "id": "rec3NIxfPRvPvoWkT",
      "fields": {
        "ipAddress": "192.168.1.170",
        "enabled": true,
        "groupSelect": ["Group-A"],
        "Name": "Controller_1",
        "nameLink": "242606363309393"
      }
    }
  ]
}
```

### Ownership Recommendation

Recommended production ownership:

- a separate Airtable export/sync process owns producing these three JSON files
- `mqtt_schedule` owns consuming and validating them

This keeps the scheduler service stable while the upstream export mechanism evolves independently.

### Access Users Export Contract

Expected file:

- `/etc/mqtt_schedule/airtable_access_users.json`

Fields used by access control:

- `firstName`
- `lastName`
- `enabled`
- `accessGroups`
- `pinCode`
- `pinNumber`
- `cardNumber`
- `faceId`

Minimal valid example:

```json
{
  "records": [
    {
      "id": "recAccess1",
      "fields": {
        "firstName": "John",
        "lastName": "Baird",
        "enabled": "true",
        "accessGroups": ["group1"],
        "pinNumber": "12345"
      }
    }
  ]
}
```

### Validation Command

Use this command before trusting newly updated Airtable export files:

```bash
/opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --validate-airtable-files
```

Successful validation prints summaries like:

```text
airtable_file kind=schedule path=/etc/mqtt_schedule/airtable_schedule_data.json record_count=... valid_count=... ok=True
airtable_file kind=controller path=/etc/mqtt_schedule/airtable_config_data.json record_count=... valid_count=... ok=True
```

If a file is missing, malformed, or missing required structure, the command exits nonzero and prints `airtable_issue ...` lines describing the problem.
