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
from PIL import Image, ImageDraw

WIDTH, HEIGHT = 1000, 750
EYE_COLOR = (28, 156, 217)
ANGRY_COLOR = (217, 60, 40)
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
