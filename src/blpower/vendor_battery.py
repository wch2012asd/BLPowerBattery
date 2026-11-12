"""Allowlisted, query-only vendor protocols. See docs/compatibility.md for sources.

Protocol constants/field layouts are independently implemented; no device settings,
pairing, firmware, LEDs or audio controls are changed.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Adapter:
    name: str
    matches: object
    query: object


def parse_arctis(response):
    # Reject unrelated notifications and short or invalid responses.
    if len(response) < 8 or response[:2] != b"\x06\x18" or response[2] > 100:
        return None
    return {"battery": response[2], "charging": None}


def arctis(device, identity):
    response = device.exchange(b"\x06\x18", lambda r: len(r) >= 8 and r[:2] == b"\x06\x18", timeout=0.8)
    value = parse_arctis(response)
    if value is None:
        return []
    return [dict(value, name=device.info["name"], instance_id=identity, source="steelseries-arctis7")]


def hidpp_request(device, slot, feature_index, function, parameters=b""):
    # Software ID 0xA distinguishes our replies from most notifications/clients.
    address = (function << 4) | 0xA
    request = bytes((0x11, slot, feature_index, address)) + parameters
    def matches(r):
        if len(r) < 7 or r[0] not in (0x10, 0x11) or r[1] != slot:
            return False
        return ((r[2] == feature_index and r[3] == address)
                or (r[2] in (0x8F, 0xFF) and r[3:5] == bytes((feature_index, address))))
    response = device.exchange(request.ljust(20, b"\x00"), matches, timeout=0.15)
    if response[2] in (0x8F, 0xFF):
        return None
    return response[4:]


def parse_hidpp_status(payload):
    # 0x1000 reports zero when the percentage is unknown; don't display it as empty.
    if payload is None or len(payload) < 3 or not 1 <= payload[0] <= 100:
        return None
    status = payload[2]
    if status not in (0, 1, 2, 3, 4):
        return None
    return dict(battery=payload[0], charging=status in (1, 2), battery_status=status)


def parse_hidpp_unified(payload):
    # Unified battery may report a coarse level instead of a percentage. Keep
    # that unknown rather than inventing 5/20/50/100 percent from a level enum.
    if payload is None or len(payload) < 4:
        return None
    return parse_hidpp_status(payload)


def logitech(device, identity):
    readings = []
    # Each paired device has its own feature table and battery; never use receiver
    # identity alone or take the highest battery among receiver slots.
    for slot in range(1, 7):
        try:
            for feature_id, function, parse in ((0x1004, 1, parse_hidpp_unified),
                                                 (0x1000, 0, parse_hidpp_status)):
                feature = hidpp_request(device, slot, 0, 0, feature_id.to_bytes(2, "big"))
                if not feature or feature[0] == 0:
                    continue
                value = parse(hidpp_request(device, slot, feature[0], function))
                if value:
                    readings.append(dict(value, name=f"Logitech 无线设备 {slot}",
                                         instance_id=f"{identity}#slot={slot}",
                                         source="logitech-hidpp20", slot=slot))
                    break
        except (OSError, ValueError) as exc:
            # An offline slot must not prevent reading another paired device.
            if hasattr(device, "vendor_errors"):
                device.vendor_errors.append(f"slot {slot}: {type(exc).__name__}: {exc}")
            continue
    return readings


ADAPTERS = (
    Adapter("steelseries-arctis7", lambda d: d["vid"] == 0x1038
            and d["pid"] in (0x1260, 0x12AD) and d.get("interface") == 5
            and d["usage_page"] >= 0xFF00, arctis),
    Adapter("logitech-hidpp20", lambda d: d["vid"] == 0x046D
            and d["pid"] in (0xC52B, 0xC532, 0xC539)
            and (d["usage_page"], d["usage"]) == (0xFF00, 2), logitech),
)


def match_adapter(info):
    return next((adapter for adapter in ADAPTERS if adapter.matches(info)), None)


def read_vendor(device, identity, adapter=None):
    selected = match_adapter(device.info)
    if selected is None or (adapter is not None and selected is not adapter):
        return []
    return selected.query(device, identity)
