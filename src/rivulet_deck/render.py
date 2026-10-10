from collections.abc import Sequence

from PIL import Image, ImageColor, ImageDraw, ImageFont
from StreamDeck.Devices.StreamDeck import StreamDeck

_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_BACKGROUND = "#12161c"
_FOREGROUND = "#f7f8f8"
_MUTED = "#8fa1b3"
_TREND_TRACK = "#242b35"

# The trend band is drawn this many times larger and downscaled: a 1-pixel line at 96x96 is
# too jagged and too dim to read as a trend.
_TREND_SCALE = 3
_TREND_FILL = 0.30
_TREND_DOT = 2


def _font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _fit_font(
    draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int
) -> ImageFont.ImageFont:
    size = max(8, max_height // 2)
    while size > 8:
        font = _font(size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        if right - left <= max_width and bottom - top <= max_height:
            return font
        size -= 1
    return _font(8)


def _draw_centred(
    deck_format: dict, text: str, background: str, foreground: str
) -> Image.Image:
    width, height = deck_format["size"]
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    font = _fit_font(draw, text, int(width * 0.9), int(height * 0.8))
    draw.text((width / 2, height / 2), text, font=font, fill=foreground, anchor="mm")
    return image


def render_key(
    deck: StreamDeck,
    label: str,
    background: str = _BACKGROUND,
    foreground: str = _FOREGROUND,
) -> Image.Image:
    return _draw_centred(deck.key_image_format(), label, background, foreground)


def _mix(color: str, background: str, weight: float) -> tuple[int, int, int]:
    target = ImageColor.getrgb(color)
    base = ImageColor.getrgb(background)
    return tuple(
        round(part * weight + other * (1.0 - weight))
        for part, other in zip(target, base, strict=True)
    )


def _trend_points(
    samples: Sequence[float], width: int, height: int
) -> list[tuple[float, float]]:
    """Map a window of fractions onto the band, stretched to its own min..max.

    The oldest reading sits on the left, the newest on the right, and every point is inset by
    the marker radius so nothing is clipped by the edge of the band.
    """
    low, high = min(samples), max(samples)
    span = high - low
    last = len(samples) - 1
    inset_x = _TREND_DOT * _TREND_SCALE
    inset_y = max(1, height // 8)
    floor = height - 1 - inset_y
    ceiling = inset_y

    if span <= 1e-9:
        levels = [(floor + ceiling) / 2] * len(samples)
    else:
        levels = [floor - (value - low) / span * (floor - ceiling) for value in samples]

    # A single reading has no span to spread across, so it lands on the right edge: the graph
    # grows leftwards from "now" as history accumulates.
    return [
        (
            width - 1 - inset_x if last == 0 else inset_x + index * (width - 1 - 2 * inset_x) / last,
            level,
        )
        for index, level in enumerate(levels)
    ]


def _draw_trend(
    image: Image.Image,
    band: tuple[int, int, int, int],
    samples: Sequence[float],
    color: str,
) -> None:
    """The recent history as a filled sparkline along the bottom of the key."""
    left, top, right, bottom = band
    ImageDraw.Draw(image).rectangle(band, fill=_TREND_TRACK)
    if not samples:
        return

    width = (right - left + 1) * _TREND_SCALE
    height = (bottom - top + 1) * _TREND_SCALE
    canvas = Image.new("RGB", (width, height), _TREND_TRACK)
    draw = ImageDraw.Draw(canvas)
    points = _trend_points(samples, width, height)

    if len(points) > 1:
        area = [*points, (points[-1][0], height - 1), (points[0][0], height - 1)]
        draw.polygon(area, fill=_mix(color, _TREND_TRACK, _TREND_FILL))
        draw.line(points, fill=ImageColor.getrgb(color), width=2 * _TREND_SCALE)

    radius = _TREND_DOT * _TREND_SCALE
    x, y = points[-1]
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=ImageColor.getrgb(color))
    image.paste(canvas.resize((right - left + 1, bottom - top + 1), Image.LANCZOS), (left, top))


def render_metric(
    deck: StreamDeck,
    label: str,
    value: str,
    unit: str = "",
    foreground: str = _FOREGROUND,
    samples: Sequence[float] = (),
) -> Image.Image:
    """Label top-left, unit top-right, value centred above a trend sparkline along the bottom."""
    width, height = deck.key_image_format()["size"]
    image = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)

    padding = max(3, height // 16)
    trend_height = max(14, height // 4)
    trend_bottom = height - padding
    trend_top = trend_bottom - trend_height

    small = _font(max(9, height // 8))
    draw.text((padding, padding), label, font=small, fill=_MUTED, anchor="lt")
    label_bottom = draw.textbbox((padding, padding), label, font=small, anchor="lt")[3]
    if unit:
        draw.text((width - padding, padding), unit, font=small, fill=_MUTED, anchor="rt")

    value_top = label_bottom + max(2, height // 32)
    value_height = trend_top - value_top - max(2, height // 48)
    font = _fit_font(draw, value, width - 2 * padding, value_height)
    draw.text(
        (width / 2, value_top + value_height / 2), value, font=font, fill=foreground, anchor="mm"
    )

    _draw_trend(image, (padding, trend_top, width - padding, trend_bottom), samples, foreground)
    return image


def render_screen(
    deck: StreamDeck,
    text: str,
    background: str = _BACKGROUND,
    foreground: str = _FOREGROUND,
) -> Image.Image:
    return _draw_centred(deck.screen_image_format(), text, background, foreground)
