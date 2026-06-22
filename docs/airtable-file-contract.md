## Airtable File Contract

The current `mqtt_schedule` rewrite treats Airtable exports as a file-based upstream contract.

This means `mqtt_schedule` does not yet fetch Airtable directly. Instead, another process or manual export step must keep these files current:

- `/etc/mqtt_schedule/airtable_schedule_data.json`
- `/etc/mqtt_schedule/airtable_config_data.json`

The scheduler service consumes those files as its source of truth.

### Why This Contract Exists

This keeps the scheduler service focused on:

- evaluating schedules
- applying irrigation/weather policy
- publishing MQTT commands
- running the Linux service loop

It also lets us replace the legacy system incrementally instead of mixing Airtable API concerns into the already-working runtime path.

### Required Top-Level Shape

Both files must be JSON objects with a top-level `records` array:

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

- a separate Airtable export/sync process owns producing these two JSON files
- `mqtt_schedule` owns consuming and validating them

This keeps the scheduler service stable while the upstream export mechanism evolves independently.

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
