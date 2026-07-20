#!/usr/bin/env python3
"""
Generates the emotion-eye GIFs shown on pib's display, in the same style
as the original pib-eyes-animated.gif (blue ring-eyes on black, 1000x750,
with a periodic blink). Run this script from its own directory whenever
the graphics should be regenerated:

    python3 generate_emotion_eyes.py

The results are committed as normal static images and baked into the
ros-display docker image - the script only exists so nobody has to draw
the emotions by hand in a graphics program.

Sizing: the display node stretches this 1000x750 canvas to fill the whole
physical screen (see display.py's GuiApplication._show_static_image /
_load_frames_into_queue, which always resize to the screen's exact pixel
size). So "using the full width" is about how much of THIS canvas the eyes
occupy, not a display setting - the eyes below span ~88% of the canvas
width, matching the size of the original neutral animation's eyes.
"""
import math
from PIL import Image, ImageDraw

WIDTH, HEIGHT = 1000, 750
EYE_COLOR = (28, 156, 217)
ANGRY_COLOR = (217, 60, 40)
HEART_COLOR = (230, 40, 90)
STAR_COLOR = (250, 200, 30)
# Deutlich heller als reines Schwarz - eine "coole" Sonnenbrille in fast
# derselben Farbe wie der Hintergrund war auf dem Display quasi unsichtbar.
COOL_COLOR = (45, 48, 62)
COOL_HIGHLIGHT_COLOR = (140, 150, 175)
BG = (0, 0, 0)
STROKE = 60  # ring thickness
CX_L, CX_R = 260, 740  # eye centers - spans ~88% of the canvas width
CY = 375
RX, RY = 200, 250  # eye radii (upright ovals, same aspect as the original)

BLINK_MS = 120
OPEN_MS = 2600


def _canvas():
    im = Image.new("RGB", (WIDTH, HEIGHT), BG)
    return im, ImageDraw.Draw(im)


def _ellipse(d, cx, cy, rx, ry, color=EYE_COLOR, width=STROKE):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=color, width=width)


def _arc(d, cx, cy, rx, ry, start, end, color=EYE_COLOR, width=STROKE):
    d.arc([cx - rx, cy - ry, cx + rx, cy + ry], start=start, end=end, fill=color, width=width)


def _line(d, p1, p2, color=EYE_COLOR, width=STROKE):
    d.line([p1, p2], fill=color, width=width)


def closed_frame(color=EYE_COLOR):
    """blink frame: two horizontal lines"""
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        _line(d, (cx - RX, CY), (cx + RX, CY), color=color)
    return im


def neutral_frame():
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        _ellipse(d, cx, CY, RX, RY)
    return im



# max radius that keeps left/right shapes from touching in the middle:
# half the distance between eye centers, minus a visible gap
_MAX_WIDE_RX = (CX_R - CX_L) // 2 - 30  # = 210


def happy_frame():
    """upper arcs like ^ ^ - classic smiling eyes"""
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        _arc(d, cx, CY + 100, _MAX_WIDE_RX, RY, 180, 360)
    return im


def sad_frame():
    """droopy lids: flat-ish top, arc opens downwards + small tear (left)"""
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        _arc(d, cx, CY - 100, _MAX_WIDE_RX, RY, 0, 180)
    # tear drop under the left eye
    d.ellipse([CX_L - 30, CY + 230, CX_L + 30, CY + 320], fill=EYE_COLOR)
    return im


def angry_frame():
    """red rings with slanted brows towards the nose"""
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        _ellipse(d, cx, CY + 35, RX, RY - 55, color=ANGRY_COLOR)
    # brows: inner ends lower, angled towards the nose
    _line(d, (CX_L - RX - 30, CY - 330), (CX_L + RX + 10, CY - 190), color=ANGRY_COLOR)
    _line(d, (CX_R - RX - 10, CY - 190), (CX_R + RX + 30, CY - 330), color=ANGRY_COLOR)
    return im


def surprised_frame():
    """big wide circles with a small filled pupil"""
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        _ellipse(d, cx, CY, _MAX_WIDE_RX, RY + 40)
        d.ellipse([cx - 45, CY - 45, cx + 45, CY + 45], fill=EYE_COLOR)
    return im


def sleepy_frame():
    """half-closed: lower half of the ring plus a straight lid"""
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        _arc(d, cx, CY, RX, RY - 70, 0, 180)
        _line(d, (cx - RX, CY), (cx + RX, CY))
    return im


def _heart(d, cx, cy, s, color):
    """filled heart shape centered at (cx, cy) - two round lobes on top and
    a long triangle beneath tapering to a sharp point.

    The lobes must genuinely OVERLAP (lobe_dx < r by a healthy margin) - an
    earlier version had them merely touching (lobe_dx == r), which looked
    right in a small preview but left a visible triangular hole between the
    lobes on the real display (rasterization doesn't render a hairline
    tangent as solid). The polygon's top edge sits a little ABOVE the
    lobes' own notch point (their circle-circle intersection) as extra
    safety margin against anti-aliasing slivers there."""
    r = s * 0.42
    lobe_dx = r * 0.65
    lobe_cy = cy - s * 0.42
    for sign in (-1, 1):
        lcx = cx + sign * lobe_dx
        d.ellipse([lcx - r, lobe_cy - r, lcx + r, lobe_cy + r], fill=color)
    notch_y = lobe_cy - math.sqrt(max(r * r - lobe_dx * lobe_dx, 0))
    base_y = notch_y - s * 0.03
    base_half_width = lobe_dx + r * 0.98
    d.polygon(
        [
            (cx - base_half_width, base_y),
            (cx + base_half_width, base_y),
            (cx, cy + s * 1.2),
        ],
        fill=color,
    )


def heart_frame():
    """classic "in love" eyes: filled pink/red hearts instead of pupils"""
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        _heart(d, cx, CY, RX * 0.95, HEART_COLOR)
    return im


def _star_points(cx, cy, outer_r, inner_r, points=5, rotation_deg=-90):
    """vertices of a 5-pointed star, alternating outer/inner radius"""
    pts = []
    step = math.pi / points
    start = math.radians(rotation_deg)
    for i in range(points * 2):
        r = outer_r if i % 2 == 0 else inner_r
        angle = start + i * step
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def star_frame():
    """starstruck/amazed eyes: filled yellow stars instead of pupils"""
    im, d = _canvas()
    for cx in (CX_L, CX_R):
        pts = _star_points(cx, CY, RX * 0.95, RX * 0.42)
        d.polygon(pts, fill=STAR_COLOR)
    return im


def cool_frame():
    """sunglasses: two dark rounded-rect lenses joined by a bridge, each with
    a small glint highlight so the lenses actually stand out against the
    black canvas (a near-black fill on black was invisible on the display)."""
    im, d = _canvas()
    lens_w, lens_h = RX * 1.3, RY * 0.75
    for cx in (CX_L, CX_R):
        d.rounded_rectangle(
            [cx - lens_w / 2, CY - lens_h / 2, cx + lens_w / 2, CY + lens_h / 2],
            radius=28,
            fill=COOL_COLOR,
        )
        gx, gy = cx - lens_w * 0.22, CY - lens_h * 0.22
        gw, gh = lens_w * 0.22, lens_h * 0.22
        d.ellipse(
            [gx - gw / 2, gy - gh / 2, gx + gw / 2, gy + gh / 2],
            fill=COOL_HIGHLIGHT_COLOR,
        )
    _line(d, (CX_L + lens_w / 2, CY), (CX_R - lens_w / 2, CY), color=COOL_COLOR, width=18)
    return im


def wink_frame():
    """one eye happy (smiling arc), the other closed - a playful wink"""
    im, d = _canvas()
    _arc(d, CX_L, CY + 100, _MAX_WIDE_RX, RY, 180, 360)
    _line(d, (CX_R - RX, CY), (CX_R + RX, CY))
    return im


def save_gif(name, open_frame, blink_color=EYE_COLOR):
    frames = [open_frame, closed_frame(blink_color), open_frame.copy()]
    durations = [OPEN_MS, BLINK_MS, OPEN_MS]
    frames[0].save(
        name,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
    )
    print("wrote", name)


if __name__ == "__main__":
    save_gif("pib-eyes-happy.gif", happy_frame())
    save_gif("pib-eyes-sad.gif", sad_frame())
    save_gif("pib-eyes-angry.gif", angry_frame(), blink_color=ANGRY_COLOR)
    save_gif("pib-eyes-surprised.gif", surprised_frame())
    save_gif("pib-eyes-sleepy.gif", sleepy_frame())
    save_gif("pib-eyes-heart.gif", heart_frame(), blink_color=HEART_COLOR)
    save_gif("pib-eyes-star.gif", star_frame(), blink_color=STAR_COLOR)
    save_gif("pib-eyes-cool.gif", cool_frame(), blink_color=COOL_COLOR)
    save_gif("pib-eyes-wink.gif", wink_frame())
