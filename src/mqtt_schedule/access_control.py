from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .domain import AccessDecision, AccessRequest


@dataclass(frozen=True)
class AccessUserRecord:
    record_id: str
    first_name: str
    last_name: str
    access_groups: list[str]
    pin_code: str | None
    pin_number: str | None
    card_number: str | None
    face_id: str | None
    enabled: bool

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or "Unknown"


class AccessUserRepository(Protocol):
    def find_enabled_user_by_credential(self, credential: str) -> AccessUserRecord | None:
        ...


class FileAccessUserRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def find_enabled_user_by_credential(self, credential: str) -> AccessUserRecord | None:
        if not credential:
            return None
        for record in self.list_users():
            if not record.enabled:
                continue
            if credential in {
                record.pin_code,
                record.pin_number,
                record.card_number,
                record.face_id,
            }:
                return record
        return None

    def list_users(self) -> list[AccessUserRecord]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        users: list[AccessUserRecord] = []
        for item in raw.get("records", []):
            fields = dict(item.get("fields") or {})
            users.append(
                AccessUserRecord(
                    record_id=str(item.get("id", "")),
                    first_name=_string_value(fields.get("firstName")),
                    last_name=_string_value(fields.get("lastName")),
                    access_groups=_string_list(fields.get("accessGroups")),
                    pin_code=_string_or_none(fields.get("pinCode")),
                    pin_number=_string_or_none(fields.get("pinNumber")),
                    card_number=_string_or_none(fields.get("cardNumber")),
                    face_id=_string_or_none(fields.get("faceId")),
                    enabled=_bool_value(fields.get("enabled")),
                )
            )
        return users


class AccessDecisionService:
    def __init__(
        self,
        *,
        repository: AccessUserRepository,
        access_groups: list[str],
    ) -> None:
        self.repository = repository
        self.access_groups = access_groups

    def decide(self, request: AccessRequest) -> AccessDecision:
        number_used = next(
            (
                value
                for value in (
                    request.pin_code,
                    request.pin_number,
                    request.card_number,
                    request.face_id,
                )
                if value
            ),
            None,
        )

        if not number_used:
            return AccessDecision(
                granted=False,
                full_name="Unknown",
                matched_group=None,
                matched_credential=None,
            )

        record = self.repository.find_enabled_user_by_credential(number_used)
        if record is None:
            return AccessDecision(
                granted=False,
                full_name="Unknown",
                matched_group=None,
                matched_credential=number_used,
            )

        matched_group = next(
            (group for group in self.access_groups if group in record.access_groups),
            None,
        )
        granted = bool(matched_group)

        return AccessDecision(
            granted=granted,
            full_name=record.full_name,
            matched_group=matched_group,
            matched_credential=number_used,
        )


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _string_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
