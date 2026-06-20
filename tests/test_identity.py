from pathlib import Path

import mqtt_schedule.identity as identity_module
from mqtt_schedule.identity import DeviceIdentity, DeviceIdentitySettings


def test_device_identity_persists_machine_derived_serial(tmp_path: Path) -> None:
    serial_file = tmp_path / "device_serial.txt"
    original_getnode = identity_module.getnode
    identity_module.getnode = lambda: 281261212083555
    try:
        identity = DeviceIdentity(DeviceIdentitySettings(serial_file=serial_file))
        first = identity.get_source_serial()
        second = identity.get_source_serial()
    finally:
        identity_module.getnode = original_getnode

    assert first == "281261212083555"
    assert second == "281261212083555"
    assert serial_file.read_text(encoding="utf-8") == "281261212083555"


def test_device_identity_respects_test_override(tmp_path: Path) -> None:
    serial_file = tmp_path / "device_serial.txt"
    identity = DeviceIdentity(
        DeviceIdentitySettings(
            serial_file=serial_file,
            source_serial_override="123456789",
        )
    )

    assert identity.get_source_serial() == "123456789"
    assert not serial_file.exists()
