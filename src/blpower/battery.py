"""Shared battery validation and provider aggregation (no GUI dependency)."""


def is_candidate(instance_id):
    return instance_id.upper().startswith(("BTH", "USB\\", "HID\\"))


def merge_readings(readings):
    """Keep first source for an exact identity; never merge by display name."""
    result = {}
    for reading in readings:
        level = reading.get("battery")
        identity = reading.get("instance_id")
        if (not isinstance(level, int) or isinstance(level, bool)
                or not 0 <= level <= 100 or not identity):
            continue
        result.setdefault(identity.casefold(), reading)
    return list(result.values())


def query_providers(providers, log=lambda message: None):
    """A failed source must not discard readings from other sources."""
    readings = []
    for name, query in providers:
        try:
            readings.extend(query())
        except Exception as exc:
            log(f"Battery provider {name} failed: {exc}")
    return merge_readings(readings)
