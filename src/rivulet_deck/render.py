from PIL import Image, ImageDraw, ImageFont
from StreamDeck.Devices.StreamDeck import StreamDeck

_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_BACKGROUND = "#12161c"
_FOREGROUND = "#f7f8f8"
_MUTED = "#8fa1b3"
_BAR_TRACK = "#242b35"


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


def render_metric(
    deck: StreamDeck,
    label: str,
    value: str,
    unit: str = "",
    foreground: str = _FOREGROUND,
    fraction: float | None = None,
) -> Image.Image:
    """Label top-left, big value, unit bottom-right, optional fill bar along the bottom."""
    width, height = deck.key_image_format()["size"]
    image = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)

    padding = max(3, height // 16)
    bar_height = max(3, height // 24)
    bar_bottom = height - padding
    bar_top = bar_bottom - bar_height

    small = _font(max(9, height // 8))
    draw.text((padding, padding), label, font=small, fill=_MUTED, anchor="lt")
    label_bottom = draw.textbbox((padding, padding), label, font=small, anchor="lt")[3]

    if unit:
        unit_top = draw.textbbox((width - padding, bar_top), unit, font=small, anchor="lb")[1]
        draw.text((width - padding, bar_top), unit, font=small, fill=_MUTED, anchor="lb")
    else:
        unit_top = bar_top

    band_top = label_bottom + max(2, height // 32)
    band_height = max(bar_height, unit_top - band_top - max(2, height // 48))
    font = _fit_font(draw, value, width - 2 * padding, band_height)
    draw.text(
        (width / 2, band_top + band_height / 2), value, font=font, fill=foreground, anchor="mm"
    )

    if fraction is not None:
        draw.rectangle((padding, bar_top, width - padding, bar_bottom), fill=_BAR_TRACK)
        filled = int((width - 2 * padding) * max(0.0, min(1.0, fraction)))
        if filled > 0:
            draw.rectangle((padding, bar_top, padding + filled, bar_bottom), fill=foreground)
    return image


def render_screen(
    deck: StreamDeck,
    text: str,
    background: str = _BACKGROUND,
    foreground: str = _FOREGROUND,
) -> Image.Image:
    return _draw_centred(deck.screen_image_format(), text, background, foreground)
