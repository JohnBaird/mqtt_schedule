import json
from pathlib import Path

from mqtt_schedule.access_control import AccessDecisionService, FileAccessUserRepository
from mqtt_schedule.domain import AccessRequest


def test_file_access_user_repository_matches_enabled_user(tmp_path: Path) -> None:
    path = tmp_path / "airtable_access_users.json"
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-1",
                        "fields": {
                            "firstName": "John",
                            "lastName": "Baird",
                            "enabled": "true",
                            "pinCode": "12345",
                            "pinNumber": "12345",
                            "accessGroups": ["group1", "group2"],
                            "faceId": "620827",
                            "cardNumber": "10810",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    record = FileAccessUserRepository(path).find_enabled_user_by_credential("12345")

    assert record is not None
    assert record.full_name == "John Baird"
    assert record.card_number == "10810"


def test_access_decision_service_grants_when_group_matches(tmp_path: Path) -> None:
    path = tmp_path / "airtable_access_users.json"
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-1",
                        "fields": {
                            "firstName": "John",
                            "lastName": "Baird",
                            "enabled": "true",
                            "pinCode": "12345",
                            "pinNumber": "12345",
                            "accessGroups": ["group1", "group2"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    decision = AccessDecisionService(
        repository=FileAccessUserRepository(path),
        access_groups=["group1", "group3"],
    ).decide(
        AccessRequest(
            source_serial="242606363309393",
            destination_serial="281261212083555",
            pin_code=None,
            pin_number="12345",
            card_number=None,
            face_id=None,
        )
    )

    assert decision.granted is True
    assert decision.full_name == "John Baird"
    assert decision.matched_group == "group1"
    assert decision.matched_credential == "12345"


def test_access_decision_service_denies_when_user_group_does_not_match(tmp_path: Path) -> None:
    path = tmp_path / "airtable_access_users.json"
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-1",
                        "fields": {
                            "firstName": "John",
                            "lastName": "Baird",
                            "enabled": "true",
                            "pinCode": "12345",
                            "pinNumber": "12345",
                            "accessGroups": ["group1"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    decision = AccessDecisionService(
        repository=FileAccessUserRepository(path),
        access_groups=["group9"],
    ).decide(
        AccessRequest(
            source_serial="242606363309393",
            destination_serial="281261212083555",
            pin_code=None,
            pin_number="12345",
            card_number=None,
            face_id=None,
        )
    )

    assert decision.granted is False
    assert decision.full_name == "John Baird"
    assert decision.matched_group is None
