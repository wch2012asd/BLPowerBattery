"""Descriptor-driven standard HID battery provider, with injectable transport."""


def normalize(raw, minimum, maximum, bits):
    if raw is None or not 1 <= bits <= 32 or maximum <= minimum:
        return None
    if minimum < 0:
        raw &= (1 << bits) - 1
        if raw & (1 << (bits - 1)):
            raw -= 1 << bits
    # Out-of-range values include HID null states. Never clamp them to 0/100.
    if not minimum <= raw <= maximum:
        return None
    return round((raw - minimum) * 100 / (maximum - minimum))


def read_standard(device, identity):
    reports = {}
    failures = []
    for field in device.battery_fields():
        try:
            key = field["kind"], field["report_id"]
            if key not in reports:
                reports[key] = device.report(*key)
            value = normalize(device.value(field, reports[key]), field["minimum"],
                              field["maximum"], field["bits"])
            if value is not None:
                return dict(name=device.info["name"], instance_id=identity,
                            battery=value, source="standard-hid", charging=None), failures
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
    return None, failures
