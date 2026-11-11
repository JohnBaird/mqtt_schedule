# Daily Logging and Email Reports

## Log Location and Rotation

Live, non-dry-run `--service` execution writes Python application logs from all modules to `/var/log/mqtt_schedule/mqtt_schedule.log`. Existing console output remains in the `mqtt_schedule` systemd journal. INFO, WARNING, ERROR, and CRITICAL logging remains enabled; no existing MQTT topics, payloads, or logging verbosity are changed.

Rotation uses the unmodified standard-library `logging.handlers.TimedRotatingFileHandler`, configured with `when="midnight"`, `interval=1`, `utc=False`, and `backupCount=7`. There is no size limit or custom rotation code. The active file can grow throughout the day; rollover occurs on the first logged message after midnight in the server's local timezone. Archives are named `mqtt_schedule.log.YYYY-MM-DD`. Seven archives plus the current file are retained; the standard handler automatically removes excess matching archives during rollover. Quiet/offline days need not produce a file, so this is seven archives rather than a strict age-based purge. Restarting appends to the active file, not an empty replacement.

The unit prepares the log directory with service ownership, mode 0750, and umask 0027. File logging also precreates a new active file as 0640. The application log directory must be writable by `mqttschedule`; do not run a second live service instance or configure an external size-based logrotate rule on these files.

Log timestamps include the absolute Unix `created` time as well as a readable local timestamp, so reports can select a precise 24-hour window even across daylight-saving changes. The email schedule uses `timezone_name`; standard file rotation uses the server's local timezone. Check `timedatectl show -p Timezone` and keep these aligned if local-midnight archives are desired.

One-shot CLI commands, previews, and history imports remain console-only and do not open a live logging handler. Native systemd lifecycle/OOM/process-kill messages and failures before file logging is initialized remain in the journal. The new reports read application files, not the entire OS journal, and need no journal-reading group membership. Explicit history import can preserve historical service/journal messages as described below.

## Configuration

Add these keys to the existing `/etc/mqtt_schedule/runtime.json` object, preserving its other settings and valid commas:

```json
"log_file": "/var/log/mqtt_schedule/mqtt_schedule.log",
"log_backup_count": 7,
"daily_log_report_enabled": true,
"daily_log_report_run_immediately": false,
"daily_log_report_time": "21:00",
"daily_log_report_state_file": "/var/lib/mqtt_schedule/daily_log_report_state.json"
```

The code and example default reporting to false for a safe initial installation; explicitly enable it after previewing. Startup diagnostics normally stay false. `log_backup_count` accepts integer 1 through 365, and the report time must be zero-padded 24-hour `HH:MM`. There is no log-size setting.

Both reports require `daily_log_report_enabled`, global `email_enabled`, and a configured email transport with at least one recipient. They reuse Gmail and the nonempty `MQTT_SCHEDULE_RECEIVER_EMAIL_ADDRESS_1`/`_2` values from the private environment file. No new credentials or recipient list is introduced. Input-rule `channels` and the startup-announcement switch `email_service_start_enabled` do not control these reports.

Feature switches, retention, and report time are JSON-controlled. Optional environment path overrides are `MQTT_SCHEDULE_LOG_FILE` and `MQTT_SCHEDULE_DAILY_LOG_REPORT_STATE_FILE`; env-only loading derives report-state storage from `MQTT_SCHEDULE_STATE_DIR`. Configuration-only changes require a restart, not `pip install`.

## Report Behavior

The daily calendar check requests a report at 21:00 in `timezone_name`, not 24 hours after application startup. Its interval is exactly the preceding 86400 seconds ending at the scheduled time, including the start and excluding the end. It can span two daily files. A service starting after today's scheduled time catches up today's report once if it was not already attempted; it does not replay a backlog of older days. This daily catch-up is independent of the optional startup diagnostic. Execution can be briefly delayed by other service work or the email queue.

When `daily_log_report_run_immediately` is true, each new service process additionally requests a diagnostic covering every retained application log record before the startup cutoff, including old and previously reported issues. This normally stays off. Neither report clears logs or marks individual issues resolved.

Email bodies show CRITICAL/ERROR/WARNING counts, host, exact cutoff/window, and observed log coverage. INFO/DEBUG entries are not included as issues. A report with no issues explicitly says none were found in available logs. Missing, unreadable, unrecognized, or too-short history is identified; absence of records is never claimed as proof of a complete healthy period. Gaps while the application was not running cannot be reconstructed from application files alone.

Full issue messages and associated traceback lines are attached as redacted UTF-8 text compressed with gzip. Large details are split into numbered emails/attachments, at most 256 Ki characters of text per part; text/tracebacks may continue in the next part. Every part repeats the overall counts, so do not sum the counts across parts. No details are deliberately truncated. Preparation uses a temporary file and streams attachments one part at a time; completed temporary data is not retained as extra report logfiles. Sufficient temporary disk space is needed for the selected issue details.

Preparation and SMTP run in the existing bounded background email worker, not the MQTT callback or service calendar check. Logfile names and byte limits are snapshotted under the live logging handler's lock, then parsing continues without holding that lock. Linux open descriptors preserve the snapshot if rotation renames an archive. A large startup report can delay other queued email notifications; SMS has its own worker.

Redaction masks known configured provider passwords/tokens/API keys, their URL-encoded values, URL credentials, and labeled access credentials such as PIN/card/face fields. This is best-effort sanitization, not automatic discovery of every possible secret in arbitrary free text. Raw logs must remain private, and recipients must be authorized to see operational details.

The private report state records the last daily **attempt**, not successful delivery. It is saved before queue submission to avoid automatic duplicate reports across restarts. A crash between that claim and submission, queue rejection, shutdown, or an SMTP failure can leave a report unsent or partially sent. There is no durable outbox or automatic retry; submission is not proof of inbox delivery. Failures are logged, and subsequent daily reports can include them. Corrupt/unwritable state suppresses the daily attempt, is not overwritten automatically, and logs an error once per day/process rather than on every calendar poll. Do not delete/reset the state file as a routine update step.

## Linux Rollout

After committing/pushing the tested Windows changes, run these commands on Linux one step at a time. Stop if an installation or validation command fails. Do not run the staging `install_linux.sh` over the existing `/opt/mqtt_schedule` Git checkout.

```bash
cd /opt/mqtt_schedule
git status --short
git pull --ff-only
sudo systemctl stop mqtt_schedule
sudo /opt/mqtt_schedule/.venv/bin/python -m pip install /opt/mqtt_schedule
sudo install -d -o mqttschedule -g mqttschedule -m 0750 /var/log/mqtt_schedule
sudo install -d -m 0755 /etc/systemd/system/mqtt_schedule.service.d
sudo nano /etc/systemd/system/mqtt_schedule.service.d/logging.conf
```

Inspect any local source changes before pulling. Add this dedicated unit drop-in, preserving existing unit customizations; if `logging.conf` already exists, inspect it before editing:

```ini
[Service]
LogsDirectory=mqtt_schedule
LogsDirectoryMode=0750
UMask=0027
StandardOutput=journal
StandardError=journal
```

New staging installations receive equivalent settings in the shipped unit. For the Git-based installation, the drop-in avoids overwriting the current base unit. Do not change the service account to root.

### Optional One-Time Journal Import

Perform this only before the first file-logging start, with the service stopped and no matching application logfiles present. New logging cannot backfill history by itself. The command imports journal JSON from the retained service history into the same standard daily filenames, including the current file when applicable. It never overwrites existing files or deletes source journal data.

```bash
sudo journalctl -u mqtt_schedule --since "7 days ago" -o json --no-pager |
  sudo -u mqttschedule /opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --import-log-history
```

The import examines the application's textual Python level before journal priority, because historical stream messages can have journal priority INFO despite containing WARNING/ERROR text. Native historical journal entries use their recorded priority. Python traceback continuation lines are preserved. Data outside the configured archive-date retention is skipped. The journal itself is unchanged.

If logs already exist, skip this step rather than deleting or overwriting them. If import fails partway through, it can leave partial new files: stop and inspect the error before continuing; do not rerun blindly. If no history is imported, initial daily reports will note that available history does not yet cover 24 hours. The original journal remains available independently.

### Preview and Enable

Edit the runtime keys above and keep provider credentials in the existing protected environment file. Preview commands make no API, SMTP, SMS, or MQTT calls and do not change the daily-attempt state:

```bash
sudo /opt/mqtt_schedule/.venv/bin/python -m json.tool /etc/mqtt_schedule/runtime.json >/dev/null
sudo -u mqttschedule /opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --preview-log-report
sudo -u mqttschedule /opt/mqtt_schedule/.venv/bin/python -m mqtt_schedule --config /etc/mqtt_schedule/runtime.json --preview-log-report --log-report-all-history
sudo systemctl daemon-reload
sudo systemctl start mqtt_schedule
sudo journalctl -u mqtt_schedule --since "2 minutes ago" -o cat --no-pager | grep -E 'file_logging|daily_log_report|startup_log_report|email_log_report'
```

Preview output shows the email summaries and attachment names/sizes, not raw details or credentials. To test actual email before 21:00, temporarily set `daily_log_report_run_immediately` true, restart once, inspect the report and attachments in the configured inboxes, then restore false and restart. The ordinary service-start announcement is a separate email. Restarting also resets the existing input-alert notification cooldowns, as previously agreed.

No journal group membership or new credentials are required. Config-only edits need no install. Updating this Python implementation requires installing the package before restarting.

## Reading Logs

Follow the readable active file by name so rotation is handled:

```bash
sudo tail -n 200 -F /var/log/mqtt_schedule/mqtt_schedule.log
sudo grep -E ' (WARNING|ERROR|CRITICAL) ' /var/log/mqtt_schedule/mqtt_schedule.log
sudo journalctl -u mqtt_schedule -n 200 -f
```

`grep` shows issue header lines only; the report includes their traceback continuations. Do not rely on `journalctl -p warning` for historical Python stream messages, whose native journal priority may not match the textual level. The application file and report parser retain the actual Python level. The service journal remains the place to inspect native systemd events and very early startup failures.

Reference: [standard Python daily rotation](https://docs.python.org/3.10/library/logging.handlers.html#timedrotatingfilehandler) and [standard MIME attachments](https://docs.python.org/3.10/library/email.message.html#email.message.EmailMessage.add_attachment).
