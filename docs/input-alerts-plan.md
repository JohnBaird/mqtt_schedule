# Airtable Input Alert Plan

Status: optional Airtable sync, validation, backups, input-edge decoding, missing-rule warnings, bounded persisted duplicate suppression, and SMS/email dispatch are implemented. Input-alert execution is off by default and requires Linux commissioning. Startup SMS and Gmail email remain independently controlled.

## Ownership

Use a new `input-alerts` table in the same Airtable base as `irrigation-config`. Airtable owns the editable alert rules; the Linux service fetches those records through the existing API integration and saves a validated local JSON export. No Airtable script or automation is needed to generate a file.

The controller linked from each rule must exist and be enabled in `irrigation-config`. The alert table does not introduce a second controller registry. Reuse the existing controller export to resolve Airtable controller record IDs to MQTT serial numbers.

Keep the following separation:

| Location | Responsibility |
| --- | --- |
| `/etc/mqtt_schedule/airtable_config_data.json` | Existing controller identity and authoritative enablement |
| `/etc/mqtt_schedule/airtable_input_alerts.json` | Downloaded input-alert rules |
| `/etc/mqtt_schedule/runtime.json` | Feature switches, table/file settings, and sync interval |
| `/etc/mqtt_schedule/mqtt_schedule.env` | Provider credentials and private notification recipients |
| `/var/lib/mqtt_schedule/airtable_backup/` | Validated last-known-good rule snapshot |
| `/var/lib/mqtt_schedule/input_alert_state.json` | Bounded duplicate-report state, separate from editable rules |

## Airtable Table

Create a table named exactly `input-alerts`, with these case-sensitive field names:

| Field | Airtable type | Contract |
| --- | --- | --- |
| `Name` | Primary single line text | Human-readable rule name |
| `enabled` | Checkbox | Same convention as other tables; unchecked or omitted means disabled |
| `controller` | Link to another record | Exactly one link to `irrigation-config`; turn off multiple-record selection |
| `inputCategory` | Single line text | Exact payload category, for example `Digital GPIO` |
| `inputIndex` | Number, integer display | Zero-based input index; use `0` through `7` for the eight-input RP2350 |
| `edge` | Single select | Exact choices `positive` and `negative` |
| `channels` | Multiple select | Exact choices `sms` and `email`; empty means no sends |
| `message` | Long text | Plain message text, not executable code or a template expression |

One row represents one controller, input category, input index, and direction. This allows a positive edge to use SMS while the negative edge uses email or both. No row means no notification for that combination, but a new edge without a matching entry must generate a warning as specified below. Reject conflicting enabled duplicates rather than sending multiple copies accidentally.

Follow the existing exports' field spelling and casing: `Name` and lowercase `enabled` (not `enable`). Controllers, schedules, access users, and input alerts share the same enabled-value parser: boolean `true` and legacy text `"true"` (case-insensitive, ignoring surrounding whitespace) enable a row. Boolean/text false, missing fields, and other values leave it disabled. Use an Airtable checkbox for new tables; legacy text support preserves compatibility. The disabled reference file is `deploy/examples/airtable_input_alerts.example.json`, alongside the three existing table examples.

Phone numbers, email addresses, passwords, and API tokens do not belong in this table. The initial implementation uses the recipients already configured for each channel on the server. Per-rule recipient groups can be designed separately if required.

### First Two Rows

For controller serial `44864172347607`, link the actual corresponding `irrigation-config` record. Do not type the serial into the linked field as a replacement for creating/selecting that controller record.

| Name | enabled | inputCategory | inputIndex | edge | channels | message |
| --- | --- | --- | --- | --- | --- | --- |
| RP2350 input 0 positive | unchecked | Digital GPIO | 0 | positive | sms | Input 0 positive edge |
| RP2350 input 0 negative | unchecked | Digital GPIO | 0 | negative | sms, email | Input 0 negative edge |

Enable only these two rows for the first live commissioning run, leaving other rows disabled. Physical meanings such as door open/closed depend on wiring and polarity and must be assigned deliberately. Keep `input_alerts_enabled` false until the code and local rule validation are ready.

## JSON Contract

Preserve the existing Airtable export shape: a top-level `records` array, with each record containing `id` and `fields`. Linked controller values are Airtable record IDs, not MQTT serials. For example:

```json
{
  "records": [
    {
      "id": "recExampleInputAlert",
      "fields": {
        "Name": "RP2350 input 0 negative",
        "enabled": false,
        "controller": ["recExampleController"],
        "inputCategory": "Digital GPIO",
        "inputIndex": 0,
        "edge": "negative",
        "channels": ["sms", "email"],
        "message": "Input 0 negative edge"
      }
    }
  ]
}
```

The example IDs are placeholders. The linked controller's `id` comes from the controller export, and its `fields.nameLink` supplies the serial used in MQTT topics. An unchecked checkbox may be absent in an actual API response; interpret it as `false`.

Validate all fetched pages and enabled rules before atomically replacing the active local export. Reuse unchanged-file detection and private last-known-good backups. A complete empty export is valid and removes all input-alert rules. A failed or invalid fetch keeps the previous validated export; report that failure visibly so operators know rule changes have not taken effect.

## Edge Interpretation

Controllers may publish `stc_input_status_response` either in reply to a scheduled request or spontaneously when an input changes. Process both through the same inbound path on arrival, without requiring an outstanding request or waiting for the next poll. Keep the existing MQTT topic and payload contracts unchanged.

Treat `positive_edges` and `negative_edges` as independent bitmasks, not input indexes or event counts:

| Input index | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Bit value | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 |

Test an input using `mask & (1 << input_index)`. For example, `negative_edges=5` identifies inputs 0 and 2; `positive_edges=130` identifies inputs 1 and 7. Zero means no edge of that direction.

A currently active input is not itself a new edge. The supplied example has `inputActiveBitmap=1` but both edge masks are zero, so it must not send a new edge alert. Process both directions independently when both masks contain the same bit. Such a report does not reveal the order of those edges or how many repeated transitions occurred between reports.

Confirmed by the controller owner for serial `44864172347607`: the controller automatically clears the reported edge flags after publishing the report and receiving the broker's acknowledgment. The scheduler does not send a separate edge-reset command. Process each set bit in each distinct report as an edge notification candidate; do not require an intervening zero-mask report before accepting a later event on the same input.

Broker acknowledgment confirms receipt by the broker, not processing by the scheduler or delivery of an SMS/email. Application duplicate suppression and any future delivery guarantees must therefore be handled separately. Do not assume other controller firmware uses the same clearing behavior without confirming its contract.

Suppress duplicate copies using the controller, category, and incoming `_iD`; the whole report is claimed once before dispatching each input/direction it contains. Do not suppress a new report merely because its mask equals an earlier mask. Both masks must be integers from 0 through 255; an omitted mask means zero for legacy compatibility. Missing/blank IDs, missing categories, invalid timestamps/masks, and retained reports do not generate alerts. Control characters in report IDs/categories are rejected to prevent forged log lines.

`unixTime` is compared with the server clock. Reports older than `input_alerts_max_age_seconds` (default 300) or more than 60 seconds in the future are rejected. Keep controller and server clocks synchronized. Polling and unsolicited responses use the same checks, regardless of `reason`.

The state file holds hashes and receive times for at most 1024 reports, with a 24-hour retention window. Entries are replaced atomically with private file permissions; size is bounded rather than growing with history. After eviction or expiry an ID is no longer remembered, although timestamp and retained-message checks still apply. This is single-service-instance duplicate protection, not a cross-process locking mechanism. Missing state starts a new store; corrupt, unreadable, or unwritable state logs `reason=state_unavailable` and suppresses delivery without overwriting corrupt state.

The report is persisted before attempting notification queues. This avoids automatic duplicate sends across a service restart but is not a durable delivery outbox: a crash between the claim and submission, a full queue, shutdown, or a provider failure can lose an alert. There are no automatic delivery retries. `queued=true` means accepted by the background worker, not delivered to the recipient. Existing provider-submission/failure logs remain authoritative for the subsequent attempt.

### Missing-Rule Warnings

For each new admitted input-edge event with no table entry matching controller, category, input index, and direction, write a structured `WARNING` to the existing application logger. Use event name `input_alert_rule_missing` with fields `source_serial`, `inputs_category`, `input_index`, `edge`, and `report_id` (the incoming `_iD`). This supports tracing a warning back to its MQTT report without logging credentials or private recipients. Do not send an SMS or email for an unmatched event.

A zero edge mask is not a missing-rule event. Apply duplicate-report suppression before emitting warnings, so redelivery of the same report does not add copies; distinct reports remain distinct events. An explicitly disabled matching entry represents intentional suppression, not a missing entry. The implementation must preserve that distinction rather than looking only at the repository's enabled rules. Controller admission checks still apply before rule matching.

These warnings belong in the existing service journal, not a new dedicated logfile. A scheduled email summary of the day's warnings is deferred; no daily email job or immediate warning email is part of this stage. A missing/invalid rule file instead logs `reason=configuration_unavailable` and skips the report; it is not treated as a valid empty rule set.

## First Download

After the updated code has been committed, pushed, pulled, and installed into the server virtual environment, run the explicit rules-only command. It uses the existing Airtable credentials and default table name and does not require automatic sync to be enabled:

```bash
sudo -u mqttschedule bash -ec 'set -a; source /etc/mqtt_schedule/mqtt_schedule.env; set +a; exec /opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --sync-input-alerts-now'
```

Run as the service user, not as root, so new cache and private backup files remain owned by `mqttschedule`. The protected environment file should retain ownership `root:mqttschedule` and mode `640`. An explicit manual fetch works even when `airtable_sync_seconds` is zero or optional automatic input-alert sync is disabled. It fetches only `input-alerts`, including all pages, and starts no MQTT connection, scheduler loop, SMS, or email sender.

Expect an `airtable_sync kind=input_alerts` result and an `input_alerts_validation` line. With the first two rows disabled, expect `record_count=2 enabled_rules=0 ok=true`. A repeated unchanged download reports `action=unchanged`. Validate the file again without making API calls:

```bash
sudo -u mqttschedule /opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --validate-input-alerts
```

No service restart is needed just to download or validate rules after this code is installed. The files are `/etc/mqtt_schedule/airtable_input_alerts.json` and `/var/lib/mqtt_schedule/airtable_backup/airtable_input_alerts.json`. A validation or API error returns a nonzero exit status. Structural JSON errors, invalid fields on enabled rules, unresolved controller links, and conflicting enabled rules are rejected before replacing an existing export. Disabled/incomplete draft rows are allowed and do not become executable rules. Refresh the local controller export if an enabled rule refers to a controller record not yet in that cache.

The download/validation commands never execute rules, even if rows are checked. Service-mode execution separately requires `input_alerts_enabled` and the appropriate channel switches.

## Runtime Controls

Execution and optional sync settings in `runtime.json`:

```json
"input_alerts_file": "/etc/mqtt_schedule/airtable_input_alerts.json",
"input_alerts_enabled": false,
"input_alert_state_file": "/var/lib/mqtt_schedule/input_alert_state.json",
"input_alerts_max_age_seconds": 300,
"airtable_input_alerts_table": "input-alerts",
"airtable_input_alerts_sync_enabled": false,
"airtable_input_alerts_sync_run_immediately": false
```

Automatic input-alert sync is off by default and the file is never a required startup export. To add the periodic fourth sync job, set `airtable_input_alerts_sync_enabled` to `true`; it shares `airtable_sync_seconds`. `airtable_input_alerts_sync_run_immediately` controls the optional startup run only when automatic input-alert sync is enabled. Zero interval still disables all automatic Airtable calls. The explicit `--sync-airtable-now` includes input alerts only when their automatic sync is enabled; `--sync-input-alerts-now` always requests just this table.

Environment overrides follow the existing Airtable convention: `MQTT_SCHEDULE_INPUT_ALERTS_FILE`, `MQTT_SCHEDULE_AIRTABLE_INPUT_ALERTS_TABLE`, `MQTT_SCHEDULE_AIRTABLE_INPUT_ALERTS_SYNC_ENABLED`, and `MQTT_SCHEDULE_AIRTABLE_INPUT_ALERTS_SYNC_RUN_IMMEDIATELY`. `MQTT_SCHEDULE_INPUT_ALERT_STATE_FILE` overrides the state-file path; env-only loading derives its default from `MQTT_SCHEDULE_STATE_DIR`. No new API credential is required. Execution enablement and maximum age are controlled only by JSON, like the SMS/email master switches; the maximum age must be an integer from 1 through 86400 seconds.

An alert requires an enabled controller, an enabled input-alert feature and matching rule, and the corresponding channel master switch. Existing `sms_enabled` and `email_enabled` remain independent final gates. Startup notification switches apply only to startup events. Notification calls go through the existing background workers; no provider requests or Airtable fetches run inside the MQTT callback.

Input-alert dispatch is attached only to live `--service` execution; one-shot commands do not activate it and `--dry-run` opens no MQTT subscription or notification transport. The existing CLI `--only-destination` also restricts input-alert controller admission. Rules and controller enablement are re-read from local files for eligible reports, so a successful refresh applies without restarting the service. Runtime switch changes still require a restart. Each rule uses its selected channels and all existing private recipients configured for those channels; per-rule recipient groups are not implemented.

With eight controllers and sixteen rows per controller, the new table contains 128 rows. At 100 records per API page, a daily refresh adds approximately 60 calls over 30 days, excluding manual refreshes and restarts. Fetching rules must never happen once per input report. Changes made in Airtable apply after a successful refresh, not immediately.

## Implementation Order

1. Confirm the table fields; broker-ack edge clearing is confirmed for controller 44864172347607.
2. Create the two disabled test rows in Airtable.
3. Implemented: optional sync target, rules-only download/local validation commands, backups, and rules repository, with mocked API tests. First Linux download passed on November 9, 2026: two enabled rules, `ok=true`, export created and backup saved. Airtable `inputIndex` must be a Number field returning numeric `0`, not text `"0"`.
4. Implemented with automated tests: bitmask decoding for requested and unsolicited responses, controller/category matching, traceable event handling, duplicate suppression, and missing-rule warnings.
5. Implemented with fake-provider tests: matching events use existing SMS/email workers, master switches, and dry-run protection. No live provider calls were made by development tests.
6. Next, commission controller 44864172347607, input 0 only: negative, positive, zero masks, combined masks, duplicate reports, and each channel enabled/disabled independently.
7. Enable additional rules after the first controller passes live commissioning.

No existing MQTT topics or payload fields need to change. Legacy input responses without edge fields continue to be consumed without generating input-edge notifications.

## Linux Commissioning

After committing/pushing the tested Windows code, run on Linux:

```bash
cd /opt/mqtt_schedule
git pull --ff-only
sudo systemctl stop mqtt_schedule
sudo /opt/mqtt_schedule/.venv/bin/python -m pip install /opt/mqtt_schedule
sudo -u mqttschedule /opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --validate-input-alerts
sudo nano /etc/mqtt_schedule/runtime.json
```

Add the four execution/file settings shown above to the existing object, preserving valid JSON and all other settings. Set `input_alerts_enabled` to true only for the commissioning run. Leave automatic Airtable sync unchanged; it is not required to use the two downloaded rules. Verify `sms_enabled` and/or `email_enabled` for the channels being tested, and leave recipients and credentials in the protected environment file.

Check that `/var/lib/mqtt_schedule` is writable by `mqttschedule`; the state file is created automatically on the first eligible report. Do not create it as an empty file or run the service manually alongside systemd. Then:

```bash
sudo /opt/mqtt_schedule/.venv/bin/python -m json.tool /etc/mqtt_schedule/runtime.json >/dev/null
sudo systemctl start mqtt_schedule
sudo journalctl -u mqtt_schedule --since "2 minutes ago" -o cat --no-pager | grep -E 'input_alert|notification_(queued|submitted|failed|skipped)'
```

Physically trigger input 0 once in each direction and observe the unsolicited responses and matching notification logs. A fresh matching report produces `input_alert_dispatch ... queued=True` for each selected enabled/configured channel; zero masks produce no input alerts. Replaying the same report ID must not send again. A new unmatched input/direction produces `WARNING ... input_alert_rule_missing` and no notification. A deliberately disabled matching row produces neither a send nor a missing-rule warning.

To disable input processing without changing startup notifications, set only `input_alerts_enabled` to false and restart. For config-only edits no `pip install` is needed. Do not delete duplicate state as a routine update step.
