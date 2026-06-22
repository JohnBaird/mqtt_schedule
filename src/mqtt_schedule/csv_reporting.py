from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class TransactionCsvRow:
    _iD: str
    latency: str
    dateTime: str
    transactionType: str
    idNumber: str
    UniqueId: str
    fullName: str
    serialSource: str


@dataclass(frozen=True)
class TemperatureCsvRow:
    _iD: str
    dateTime: str
    serialSource: str
    ipAddress: str
    hostName: str
    sensorName: str
    tempValue: str


@dataclass(frozen=True)
class ControllerStatusCsvRow:
    serialSource: str
    eventType: str
    lastSeenAt: str
    detectedAt: str
    lastResponse: str
    lastReason: str
    thresholdSeconds: str


class RotatingCsvWriter:
    def __init__(
        self,
        *,
        file_path: Path,
        row_type: type[TransactionCsvRow] | type[TemperatureCsvRow] | type[ControllerStatusCsvRow],
        max_entries: int,
        backup_dir: Path,
        backup_count: int,
        logger: logging.Logger,
    ) -> None:
        self.file_path = file_path
        self.row_type = row_type
        self.max_entries = max_entries
        self.backup_dir = backup_dir
        self.backup_count = backup_count
        self.logger = logger
        self.header = [field.name for field in fields(row_type)]
        self._ensure_file_has_header()
        self._row_count = self._get_data_row_count()

    def write_row(self, row: TransactionCsvRow | TemperatureCsvRow) -> None:
        self._rotate_if_needed()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(asdict(row).values())
        self._row_count += 1
        self.logger.info(
            "csv_row_written path=%s rows=%s",
            self.file_path,
            self._row_count,
        )

    def _ensure_file_has_header(self) -> None:
        if self.file_path.exists() and self.file_path.stat().st_size > 0:
            return
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(self.header)

    def _get_data_row_count(self) -> int:
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            return 0
        with self.file_path.open("r", newline="", encoding="utf-8") as handle:
            line_count = sum(1 for _ in handle)
        return max(0, line_count - 1)

    def _rotate_if_needed(self) -> None:
        if self.max_entries <= 0 or self._row_count < self.max_entries:
            return
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            self._row_count = 0
            self._ensure_file_has_header()
            return

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{self.file_path.stem}_{timestamp}{self.file_path.suffix}"
        self.file_path.replace(backup_path)
        self.logger.info(
            "csv_file_rotated path=%s backup=%s rows=%s max_entries=%s",
            self.file_path,
            backup_path,
            self._row_count,
            self.max_entries,
        )
        self._ensure_file_has_header()
        self._row_count = 0
        self._prune_backups()

    def _prune_backups(self) -> None:
        if self.backup_count <= 0 or not self.backup_dir.exists():
            return
        backups = sorted(
            self.backup_dir.glob(f"{self.file_path.stem}_*{self.file_path.suffix}"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_path in backups[self.backup_count :]:
            old_path.unlink(missing_ok=True)
            self.logger.info("csv_backup_pruned path=%s", old_path)


class LegacyCsvRecorder:
    def __init__(
        self,
        *,
        transaction_writer: RotatingCsvWriter,
        temperature_writer: RotatingCsvWriter,
        controller_status_writer: RotatingCsvWriter,
    ) -> None:
        self.transaction_writer = transaction_writer
        self.temperature_writer = temperature_writer
        self.controller_status_writer = controller_status_writer

    @classmethod
    def from_settings(cls, settings) -> "LegacyCsvRecorder":
        logger = logging.getLogger("mqtt_schedule.csv_reporting")
        return cls(
            transaction_writer=RotatingCsvWriter(
                file_path=settings.transaction_csv_file,
                row_type=TransactionCsvRow,
                max_entries=settings.transaction_csv_max_entries,
                backup_dir=settings.csv_backup_dir,
                backup_count=settings.transaction_csv_backup_count,
                logger=logger,
            ),
            temperature_writer=RotatingCsvWriter(
                file_path=settings.temperature_csv_file,
                row_type=TemperatureCsvRow,
                max_entries=settings.temperature_csv_max_entries,
                backup_dir=settings.csv_backup_dir,
                backup_count=settings.temperature_csv_backup_count,
                logger=logger,
            ),
            controller_status_writer=RotatingCsvWriter(
                file_path=settings.controller_status_csv_file,
                row_type=ControllerStatusCsvRow,
                max_entries=settings.controller_status_csv_max_entries,
                backup_dir=settings.csv_backup_dir,
                backup_count=settings.controller_status_csv_backup_count,
                logger=logger,
            ),
        )

    def record_transaction_response(
        self,
        *,
        transaction_id: str,
        latency: str,
        date_time: str,
        transaction_type: str,
        id_number: str,
        unique_id: str,
        full_name: str,
        source_serial: str,
    ) -> None:
        self.transaction_writer.write_row(
            TransactionCsvRow(
                _iD=transaction_id,
                latency=latency,
                dateTime=date_time,
                transactionType=transaction_type,
                idNumber=id_number,
                UniqueId=unique_id,
                fullName=full_name,
                serialSource=source_serial,
            )
        )

    def record_temperature_response(
        self,
        *,
        message_id: str,
        date_time: str,
        source_serial: str,
        ip_address: str,
        host_name: str,
        sensor_name: str,
        temp_value: str,
    ) -> None:
        self.temperature_writer.write_row(
            TemperatureCsvRow(
                _iD=message_id,
                dateTime=date_time,
                serialSource=source_serial,
                ipAddress=ip_address,
                hostName=host_name,
                sensorName=sensor_name,
                tempValue=temp_value,
            )
        )

    def record_controller_offline_event(
        self,
        *,
        source_serial: str,
        last_seen_at: str,
        detected_at: str,
        last_response: str,
        last_reason: str,
        offline_after_seconds: int,
    ) -> None:
        self.controller_status_writer.write_row(
            ControllerStatusCsvRow(
                serialSource=source_serial,
                eventType="offline_timeout",
                lastSeenAt=last_seen_at,
                detectedAt=detected_at,
                lastResponse=last_response,
                lastReason=last_reason,
                thresholdSeconds=str(offline_after_seconds),
            )
        )

    def record_controller_online_recovered_event(
        self,
        *,
        source_serial: str,
        last_seen_at: str,
        detected_at: str,
        last_response: str,
        last_reason: str,
        online_recovery_after_seconds: int,
    ) -> None:
        self.controller_status_writer.write_row(
            ControllerStatusCsvRow(
                serialSource=source_serial,
                eventType="online_recovered",
                lastSeenAt=last_seen_at,
                detectedAt=detected_at,
                lastResponse=last_response,
                lastReason=last_reason,
                thresholdSeconds=str(online_recovery_after_seconds),
            )
        )
