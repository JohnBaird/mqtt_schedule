## Airtable File Contract

The current `mqtt_schedule` rewrite treats Airtable exports as a file-based upstream contract.

This means the scheduler runtime does not treat Airtable as its day-to-day source of truth. Instead, a separate sync step produces local JSON files that the scheduler consumes.

- `/etc/mqtt_schedule/airtable_schedule_data.json`
- `/etc/mqtt_schedule/airtable_config_data.json`
- `/etc/mqtt_schedule/airtable_access_users.json`

The scheduler service consumes those files as its source of truth.

### Why This Contract Exists

This keeps the scheduler service focused on:

- evaluating schedules
- applying irrigation/weather policy
- publishing MQTT commands
- running the Linux service loop

It also lets us replace the legacy system incrementally instead of mixing Airtable API concerns into the already-working runtime path.

### Current Sync Behavior

The rewrite now includes a separate Airtable sync path:

- manual sync:

```bash
/opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --sync-airtable-now
```

- startup safety:
  if any of the three required Airtable files are missing when `mqtt_schedule` starts, it immediately attempts an Airtable sync before continuing

- no-op overwrite protection:
  if the fetched Airtable payload is identical to the current local JSON file, the file is left untouched instead of being rewritten

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
