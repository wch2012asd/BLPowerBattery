"""Pure display helpers shared by the Qt UI and tests."""


def battery_color(level: int) -> str:
    if level >= 50:
        return "#3ee07a"
    if level >= 20:
        return "#ffce4d"
    return "#ff5b5b"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgba_a(hex_color: str, alpha_0_255: float) -> str:
    """Convert a hex color and alpha value to a Qt stylesheet rgba value."""
    red, green, blue = _hex_to_rgb(hex_color)
    alpha = max(0, min(255, int(round(alpha_0_255))))
    return f"rgba({red},{green},{blue},{alpha})"


def _pct_to_alpha(percent: float) -> float:
    """Convert and clamp opacity percentage to the 0-255 alpha range."""
    return max(0.0, min(100.0, float(percent))) / 100.0 * 255.0


def device_icon(name: str) -> str:
    normalized = name.lower()
    icon_keywords = (
        (("耳", "headphone", "earbud", "buds", "airpods"), "🎧"),
        (("mouse", "鼠标"), "🖱️"),
        (("keyboard", "键盘", "key"), "⌨️"),
        (("pen", "stylus", "笔", "pencil"), "✏️"),
        (("speaker", "音箱", "sound"), "🔊"),
        (("watch", "手表", "band", "手环"), "⌚"),
        (("phone", "手机"), "📱"),
    )
    for keywords, icon in icon_keywords:
        if any(keyword in normalized for keyword in keywords):
            return icon
    return "🔋"
