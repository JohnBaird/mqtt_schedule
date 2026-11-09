from __future__ import annotations


def enabled_value(value: object) -> bool:
    """Keep checkbox and legacy text enablement consistent across Airtable exports."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False
