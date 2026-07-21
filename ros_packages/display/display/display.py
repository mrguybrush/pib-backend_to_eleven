from queue import Queue
import base64
import gc
import logging
from dataclasses import dataclass
from io import BytesIO
from itertools import cycle
import os
import time
from threading import Thread, Timer
from typing import Iterable, Iterator, Optional

import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String, Empty
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import PIL.ImageTk
import qrcode

from tkinter import *

import requests

from datatypes.msg import DisplayImage, ImageFormat, ImageId
from datatypes.srv import ShowCustomFacialExpression
from pib_api_client import URL_PREFIX
from pib_api_client import ip_client

import os

os.environ.setdefault("DISPLAY", ":0.0")

# how long the IP-address overlay stays up at boot before switching to the
# normal eyes animation - long enough to read+type it, short enough to not
# be stuck showing it if nobody's looking.
IP_OVERLAY_SECONDS = 20.0

# Kameraspiegel waehrend der Bewegungserfassung: solange Motion Capture
# laeuft (Signal: oak_depth_control "start"/"stop", dasselbe Topic, mit dem
# die Motion-Capture-Seite den Tiefenstream schaltet), zeigt das Display
# statt der Augen das Kamerabild - die Person vor pib sieht sich dann
# direkt am Roboter, ohne auf den Browser schauen zu muessen. Gespiegelt
# wie ein echter Spiegel (sonst fuehlt sich links/rechts falsch an).
CAMERA_MIRROR_MAX_FPS = 5.0
_CAMERA_MIRROR_MIN_INTERVAL_S = 1.0 / CAMERA_MIRROR_MAX_FPS
# JPEG-Qualitaet fuers erneute Encoden nach dem Spiegeln - Display ist
# klein, 70 reicht locker und haelt die Frames leicht.
_CAMERA_MIRROR_JPEG_QUALITY = 70
# host-ip endpoint may not be reachable yet if flask-app is still doing its
# own startup (db migrations/seed) - retry a few times rather than silently
# skipping the overlay on a slow boot.
IP_FETCH_ATTEMPTS = 5
IP_FETCH_RETRY_DELAY_S = 2.0


# points to the directory, where all static images are
# stored that are managed by the display-node
STATIC_IMAGE_DIR: str = os.getenv(
    "STATIC_IMAGE_DIR",
    "/home/pib/ros_working_dir/src/display/static_images",
)


def _detect_image_format(data: bytes) -> int:
    """Sniffs the magic header to tell gif/png/jpeg apart - used for custom
    facial expressions, which (unlike the fixed emotions) can be any of the
    three (see facial_expression_controller.py's upload validation)."""
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ImageFormat.ANIMATED_GIF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ImageFormat.PNG
    if data.startswith(b"\xff\xd8\xff"):
        return ImageFormat.JPEG
    # Fall back to gif (previous hardcoded behaviour) rather than raising -
    # _show_image already resolves an unknown format_value via the "else"
    # branch (_show_static_image), which will simply fail to decode and log
    # rather than hang.
    return ImageFormat.ANIMATED_GIF


@dataclass
class ImageFile:
    """represents an image stored in the filesystem"""

    format_value: bytes
    filepath: str


@dataclass
class RawImage:
    """an image whose data was loaded into main-memory"""

    format_value: bytes
    data: bytes

    @staticmethod
    def from_display_image(display_image: DisplayImage):
        """turns a DisplayImage into a RawImage"""
        image_id = display_image.id.value
        match image_id:
            case ImageId.CUSTOM:
                return RawImage(
                    display_image.format.value, b"".join(display_image.data)
                )
            case ImageId.NONE:
                return None
            case _:
                image_file = IMAGE_ID_TO_STATIC_IMAGES.get(image_id)
                if image_file is None:
                    raise Exception(f"illegal image-id: '{image_id}'.")
                return RawImage.from_image_file(image_file)

    @staticmethod
    def from_image_file(image_file: ImageFile):
        """turns a ImageFile into a RawImage"""
        with open(image_file.filepath, "rb") as file:
            data = file.read()
        return RawImage(image_file.format_value, data)


@dataclass
class AnimationFrame:
    """represents one frame of an animated gif"""

    duration_ms: int
    photo_image: PhotoImage


class Animation:
    """can be used to iterate over the frames of an animated gif"""

    def __init__(self, data: bytes, width: int, height: int):
        """initalizes the animation, with the given image-data"""
        self._frames: Iterable[AnimationFrame] = self._as_frames(data, width, height)
        self._frame_iterator = iter(cycle(self._frames))
        self._stopped = False

    def stop(self) -> None:
        """stop the iterator"""
        self._stopped = True

    def __iter__(self) -> Iterator[AnimationFrame]:
        return self

    def __next__(self) -> AnimationFrame:
        if self._stopped:
            raise StopIteration()
        else:
            return next(self._frame_iterator)

    def _as_frames(
        self, data: bytes, width: int, height: int
    ) -> Iterable[AnimationFrame]:
        queue = Queue()
        Thread(
            target=self._load_frames_into_queue, args=(queue, data, width, height)
        ).start()
        while True:
            data, duration_ms = queue.get()
            if data is None:
                break
            yield AnimationFrame(duration_ms, PhotoImage(data=data))

    def _load_frames_into_queue(
        self, queue: Queue, data: bytes, width: int, height: int
    ) -> None:
        # This runs in a background Thread - any uncaught exception here
        # kills the thread silently (Python just logs it to stderr) WITHOUT
        # ever putting the (None, -1) sentinel into the queue. The consuming
        # generator (_as_frames) then blocks forever on queue.get(), and
        # since it's only ever advanced from the Tk main loop
        # (_show_next_frame), that hangs the ENTIRE display - no further
        # image can be shown until the process is restarted. A gif with an
        # unusual size/mode/frame count PIL trips over (rather than a
        # crash) is exactly the case that used to freeze the display this
        # way, so every exit path below explicitly puts the sentinel.
        try:
            with PIL.Image.open(BytesIO(data)) as image:
                # iterate over frames of image
                for i in range(image.n_frames):
                    # go to i-th frame of the image
                    image.seek(i)
                    # resize the current frame, to fit the screen-size
                    resized = (
                        image.resize((width, height))
                        if image.width != width or image.height != height
                        else image
                    )
                    # buffer for storing binary data of image-frames
                    data_buffer = BytesIO()
                    # save the current frame in the data-buffer
                    resized.save(data_buffer, "gif")
                    # extract data from buffer and encode bytes as base64
                    frame_data = base64.b64encode(data_buffer.getvalue())
                    # get the duration of the current frame - falls back to a
                    # sensible hold time if the gif doesn't specify one
                    # (common for a simple single-frame/static gif exported
                    # by hand, e.g. from an image editor, rather than
                    # generated with explicit per-frame durations like the
                    # other emotions here)
                    duration_ms = image.info.get("duration", 2000)
                    # yield the extracted data
                    queue.put((frame_data, duration_ms))
        except Exception:
            logging.getLogger("display").exception(
                "failed to decode/resize gif frames - showing nothing for "
                "this image instead of hanging the display"
            )
        finally:
            # 'None' -> all frames were processed (or loading failed) -
            # ALWAYS put this so the consuming generator can terminate.
            queue.put((None, -1))


# maps an image-id to its corresponding image in the filesystem
# (the emotion gifs are generated by static_images/generate_emotion_eyes.py)
IMAGE_ID_TO_STATIC_IMAGES: dict[int, ImageFile] = {
    ImageId.PIB_EYES_ANIMATED: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-animated.gif"
    ),
    ImageId.PIB_EYES_HAPPY: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-happy.gif"
    ),
    ImageId.PIB_EYES_SAD: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-sad.gif"
    ),
    ImageId.PIB_EYES_ANGRY: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-angry.gif"
    ),
    ImageId.PIB_EYES_SURPRISED: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-surprised.gif"
    ),
    ImageId.PIB_EYES_SLEEPY: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-sleepy.gif"
    ),
    ImageId.PIB_EYES_HEART: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-heart.gif"
    ),
    ImageId.PIB_EYES_STAR: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-star.gif"
    ),
    ImageId.PIB_EYES_COOL: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-cool.gif"
    ),
    ImageId.PIB_EYES_WINK: ImageFile(
        ImageFormat.ANIMATED_GIF, STATIC_IMAGE_DIR + "/pib-eyes-wink.gif"
    ),
}

# Matches pib-eyes-animated.gif's resolution/aspect ratio as a stand-in for
# the real screen's aspect ratio (GuiApplication resizes any image to the
# actual screen size regardless, but keeping the same aspect avoids
# unnecessary stretching/distortion).
_IP_OVERLAY_SIZE = (1000, 750)
# PIL.ImageFont.load_default() only accepts a 'size' kwarg (for a legible
# scalable font) from Pillow >= 10.1, not guaranteed in whatever the image
# happens to pull at build time. Instead: draw with the small built-in
# bitmap font on a canvas this many times smaller, then nearest-neighbor
# upscale the whole image - guarantees big, crisp (if blocky) text on any
# Pillow version, no bundled font file needed.
_IP_OVERLAY_UPSCALE = 4


def _centered_text(
    draw: "PIL.ImageDraw.ImageDraw",
    text: str,
    canvas_width: int,
    y: float,
    font,
    fill,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text(((canvas_width - text_width) / 2, y), text, font=font, fill=fill)


def _generate_qr_code_image(data: str, size_px: int) -> "PIL.Image.Image":
    """Renders 'data' as a QR code, scaled to a size_px x size_px square.
    Nearest-neighbor scaling keeps the module edges sharp (same reasoning
    as _IP_OVERLAY_UPSCALE above - blurring a QR code risks it not
    scanning)."""
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return image.resize((size_px, size_px), PIL.Image.NEAREST)


def _render_ip_overlay_png(ip: str) -> bytes:
    """Renders an 'IP-Adresse: x.x.x.x' image with a QR code linking to
    pib's web interface, shown at boot so the user can find pib on the
    network without a laptop already connected - or just scan the code
    with their phone."""
    width, height = _IP_OVERLAY_SIZE
    small_w, small_h = width // _IP_OVERLAY_UPSCALE, height // _IP_OVERLAY_UPSCALE
    small = PIL.Image.new("RGB", (small_w, small_h), color=(10, 12, 26))
    draw = PIL.ImageDraw.Draw(small)
    font = PIL.ImageFont.load_default()

    _centered_text(draw, "IP-Adresse", small_w, small_h * 0.08, font, (150, 155, 180))
    _centered_text(draw, ip, small_w, small_h * 0.20, font, (255, 255, 255))

    image = small.resize((width, height), PIL.Image.NEAREST)

    qr_size = int(height * 0.55)
    qr_x = (width - qr_size) // 2
    qr_y = int(height * 0.35)
    qr_image = _generate_qr_code_image(f"http://{ip}/", qr_size)
    # weisser Rahmen, damit der QR-Code auf dem dunklen Hintergrund sauber
    # scannbar bleibt (ohne Rahmen wuerde der dunkle Hintergrund direkt an
    # die aeusseren hellen QR-Module angrenzen).
    quiet_zone = 12
    PIL.ImageDraw.Draw(image).rectangle(
        [
            qr_x - quiet_zone,
            qr_y - quiet_zone,
            qr_x + qr_size + quiet_zone,
            qr_y + qr_size + quiet_zone,
        ],
        fill=(255, 255, 255),
    )
    image.paste(qr_image, (qr_x, qr_y))

    buffer = BytesIO()
    image.save(buffer, "png")
    return buffer.getvalue()


def _fetch_host_ip(log) -> Optional[str]:
    for attempt in range(IP_FETCH_ATTEMPTS):
        successful, ip = ip_client.get_host_ip()
        if successful and ip:
            return ip
        if attempt < IP_FETCH_ATTEMPTS - 1:
            time.sleep(IP_FETCH_RETRY_DELAY_S)
    log("could not fetch host IP for the startup overlay after retrying")
    return None


class GuiApplication(Frame):

    def __init__(
        self,
        parent: Widget,
        image_queue: Queue[RawImage | None],
        inital_image: RawImage,
        *args,
        **kwargs,
    ):

        self._width = kwargs.setdefault("width", 100)
        self._height = kwargs.setdefault("height", 100)

        # call to the constructor of the superclass
        Frame.__init__(self, parent, *args, **kwargs)

        # store the image_queue to poll from it for images to show
        self.image_queue = image_queue

        # define a canvas where the main-image is displayed
        self.canvas = Canvas(
            self,
            width=self._width,
            height=self._height,
            borderwidth=0,
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0)

        # the current static-image/animation that is shown is stored here
        self.current_main_content: PhotoImage | Animation | None = None

        self._show_image(inital_image)

        # time until attempt to poll next image (in milliseconds)
        self.polling_timeout_ms = 10

        # intiate periodically polling for images in the queue
        self._poll_next_image()

        # position the widget in its parent
        self.grid()

    def _show_image(self, raw_image: RawImage) -> None:
        """update the main background image"""
        self.canvas.delete("all")
        if isinstance(self.current_main_content, Animation):
            self.current_main_content.stop()
        # Dropping the last reference to the old Animation/PhotoImage frames
        # here doesn't guarantee they're actually freed on THIS thread - if
        # they're part of a reference cycle (the frame generator is a bound
        # method closing over 'self'), cleanup gets deferred to Python's
        # cyclic GC, which can run on ANY thread that happens to allocate
        # next (e.g. the new Animation's background frame-loader thread).
        # PhotoImage.__del__ calls into Tcl, which aborts the whole process
        # if invoked off the Tk main thread ("Tcl_AsyncDelete: async handler
        # deleted by the wrong thread") - reproducible simply by switching
        # the displayed image while a previous animation is still running.
        # Forcing a synchronous collect() HERE, while we're definitely still
        # on the Tk main thread (this method only runs from Tk callbacks),
        # ensures that cleanup happens now instead of being deferred to an
        # unsafe thread later.
        self.current_main_content = None
        gc.collect()
        if raw_image.format_value == ImageFormat.ANIMATED_GIF:
            self._show_animated_gif(raw_image)
        else:
            self._show_static_image(raw_image)

    def _show_animated_gif(self, raw_image: RawImage) -> None:
        animation = Animation(raw_image.data, self._width, self._height)
        self.current_main_content = animation
        self._show_next_frame(animation)

    def _show_static_image(self, raw_image: RawImage) -> None:
        with PIL.Image.open(BytesIO(raw_image.data)) as image:
            resized = image.resize((self._width, self._height))
            # tkinter.PhotoImage only understands GIF/PGM/PPM/PNG - it can't
            # decode JPEG (used by the camera-mirror feature, see
            # on_camera_frame), which raised _tkinter.TclError here and left
            # the canvas blank/white (already cleared in _show_image() right
            # before this ran). PIL.ImageTk.PhotoImage renders directly from
            # the already-decoded PIL image instead, so it works for any
            # format PIL can open.
            self.current_main_content = PIL.ImageTk.PhotoImage(resized)
        self.canvas.create_image(0, 0, image=self.current_main_content, anchor="nw")

    def _show_next_frame(self, animation: Animation) -> None:
        try:
            frame: AnimationFrame = next(animation)
        except StopIteration:
            return
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=frame.photo_image, anchor="nw")
        self.canvas.after(frame.duration_ms, self._show_next_frame, animation)

    def _poll_next_image(self) -> None:
        if self.image_queue.qsize() != 0:
            image: Optional[RawImage] = self.image_queue.get()
            if image is None:
                self.winfo_toplevel().destroy()
                return
            else:
                # if an image is received, reset the timeout to the lowest
                # possible value
                self.polling_timeout_ms = 10
                self._show_image(image)
        else:
            # if no image, was received, increase the polling timeout
            # (value is capped at 160ms)
            self.polling_timeout_ms = min(2 * self.polling_timeout_ms, 160)
        self.after(self.polling_timeout_ms, self._poll_next_image)


class DisplayNode(Node):

    def __init__(self, image_queue: Queue[RawImage | None]) -> None:

        super().__init__("display")

        self.create_subscription(
            DisplayImage, "display_image", self.on_display_image_received, 1
        )

        self.image_queue = image_queue

        pib_eyes_animated = RawImage.from_image_file(
            IMAGE_ID_TO_STATIC_IMAGES[ImageId.PIB_EYES_ANIMATED]
        )

        # --- Kameraspiegel (siehe Kommentar bei CAMERA_MIRROR_MAX_FPS) ---
        self.pib_eyes_animated = pib_eyes_animated
        self.camera_mirror_active = False
        self._last_mirror_time = 0.0
        self.create_subscription(
            String, "oak_depth_control", self.on_motion_capture_control, 10
        )
        self.create_subscription(
            String, "camera_topic", self.on_camera_frame, 1
        )

        # Auf Anfrage (z.B. Klick auf den QR-Code im Frontend) das IP+QR-
        # Overlay zeigen - Empty-Message, keine eigenen Datentypen noetig.
        self.create_subscription(
            Empty, "show_ip_overlay", self.on_show_ip_overlay, 10
        )
        self._ip_overlay_revert_timer: Optional[Timer] = None

        # Zeigt einen benutzerdefinierten Gesichtsausdruck (siehe
        # Verwaltungsseite "Gesichtsausdruecke") anhand seiner expression_id -
        # fuer Blockly-generierte Programme, die (anders als das Frontend)
        # nicht selbst per HTTP die GIF-Bytes holen und ueber ROS publishen
        # koennen. Holt die Bytes hier direkt von Flask und zeigt sie genauso
        # an wie ImageId.CUSTOM (siehe RawImage.from_display_image).
        self.create_service(
            ShowCustomFacialExpression,
            "show_custom_facial_expression",
            self.on_show_custom_facial_expression,
        )

        startup_image = self._build_ip_overlay_image() or pib_eyes_animated
        self.image_queue.put(startup_image)

        if startup_image is not pib_eyes_animated:
            # boot notice only - revert to the normal eyes animation once
            # it's had its time on screen. If a "real" image has been
            # requested via the display_image topic in the meantime, this
            # will interrupt it once; acceptable for a one-shot boot notice.
            self._revert_to_eyes_after(IP_OVERLAY_SECONDS)

        self.get_logger().info("Now Running DISPLAY")

    def _build_ip_overlay_image(self) -> Optional[RawImage]:
        """Fetches the host IP and renders the 'IP-Adresse + QR-Code'
        overlay, or None if the IP can't be determined / rendering fails."""
        ip = _fetch_host_ip(self.get_logger().warn)
        if not ip:
            return None
        try:
            return RawImage(ImageFormat.PNG, _render_ip_overlay_png(ip))
        except Exception:
            self.get_logger().exception("failed to render IP overlay image")
            return None

    def _revert_to_eyes_after(self, seconds: float) -> None:
        """(Re)starts the timer that puts the animated eyes back on screen
        after the IP/QR overlay has had its time up."""
        if self._ip_overlay_revert_timer is not None:
            self._ip_overlay_revert_timer.cancel()
        self._ip_overlay_revert_timer = Timer(
            seconds, lambda: self.image_queue.put(self.pib_eyes_animated)
        )
        self._ip_overlay_revert_timer.start()

    def on_show_ip_overlay(self, _msg: Empty) -> None:
        """Show the IP+QR overlay now (same duration as at boot), then revert
        to the eyes - triggered by the frontend when the user opens the QR
        code, so the code is scannable straight off pib's own screen."""
        overlay = self._build_ip_overlay_image()
        if overlay is None:
            return
        self.image_queue.put(overlay)
        self._revert_to_eyes_after(IP_OVERLAY_SECONDS)

    def on_display_image_received(self, display_image: DisplayImage):
        """callback function for the 'display_image'-topic subscriber"""
        try:
            raw_image = RawImage.from_display_image(display_image)
            self.image_queue.put(raw_image)
        except Exception as e:
            self.get_logger().error(f"error while showing image from topic: {e}.")

    def on_show_custom_facial_expression(
        self,
        request: ShowCustomFacialExpression.Request,
        response: ShowCustomFacialExpression.Response,
    ) -> ShowCustomFacialExpression.Response:
        try:
            reply = requests.get(
                f"{URL_PREFIX}/facial-expressions/{request.expression_id}/gif",
                timeout=5,
            )
            reply.raise_for_status()
            image_format = _detect_image_format(reply.content)
            self.image_queue.put(RawImage(image_format, reply.content))
            response.successful = True
        except Exception as e:
            self.get_logger().error(
                f"error while showing custom facial expression "
                f"'{request.expression_id}': {e}."
            )
            response.successful = False
        return response

    def on_motion_capture_control(self, msg: String):
        """Motion Capture an/aus (oak_depth_control) -> Kameraspiegel
        an/aus; beim Beenden zurueck zu den animierten Augen."""
        active = msg.data.strip().lower() == "start"
        if active == self.camera_mirror_active:
            return
        self.camera_mirror_active = active
        self.get_logger().info(f"camera mirror: active={active}")
        if not active:
            # blockierend (nicht droppend): die Augen-Wiederherstellung darf
            # nicht verloren gehen, sonst bliebe das letzte Kamerabild
            # stehen. Die GUI leert die Queue binnen ~160ms, und neue
            # Kamera-Frames kommen nicht mehr (mirror_active ist schon False).
            self.image_queue.put(self.pib_eyes_animated)

    def on_camera_frame(self, msg: String):
        """Kamera-Frame (base64-JPEG vom Kamera-Node) auf dem Display
        zeigen, solange Motion Capture laeuft - gedrosselt und horizontal
        gespiegelt (wie ein Spiegel)."""
        if not self.camera_mirror_active:
            return
        now = time.monotonic()
        if now - self._last_mirror_time < _CAMERA_MIRROR_MIN_INTERVAL_S:
            return
        self._last_mirror_time = now
        try:
            jpeg = base64.b64decode(msg.data)
            with PIL.Image.open(BytesIO(jpeg)) as image:
                mirrored = image.transpose(PIL.Image.FLIP_LEFT_RIGHT)
                buffer = BytesIO()
                mirrored.save(
                    buffer, "jpeg", quality=_CAMERA_MIRROR_JPEG_QUALITY
                )
            self._queue_image_dropping(
                RawImage(ImageFormat.JPEG, buffer.getvalue())
            )
        except Exception as e:
            self.get_logger().error(f"camera mirror frame failed: {e}")

    def _queue_image_dropping(self, image: RawImage) -> None:
        """Bild anzeigen, aber NIE blockieren: die GUI-Queue hat maxsize=1 -
        ist sie gerade voll, wird der Frame einfach verworfen (beim
        naechsten Kamera-Frame kommt ohnehin ein aktuellerer)."""
        try:
            self.image_queue.put_nowait(image)
        except Exception:
            pass


def run_gui_application(image_queue: Queue[RawImage | None]) -> None:
    while True:
        image = image_queue.get()
        if image is None:
            continue
        root = Tk()
        root.bind("<Escape>", lambda _: root.destroy())
        # Requesting fullscreen before the window manager has mapped this
        # window is a race: the WM sometimes misses/ignores the fullscreen
        # hint, leaving the taskbar and window border visible on top ("manchmal
        # sieht man oben noch die Taskleiste und den Fensterrand" - only
        # happens once per boot, since the window is reused for every image
        # afterwards). Forcing the window to be realized first gives the WM
        # an actual window to apply the hint to.
        root.update_idletasks()
        root.attributes("-fullscreen", True)
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        GuiApplication(root, image_queue, image, width=width, height=height)
        root.mainloop()


def run_display_node(image_queue: Queue[RawImage | None]) -> None:
    rclpy.init()
    executor = SingleThreadedExecutor()
    display_node = DisplayNode(image_queue)
    executor.add_node(display_node)
    executor.spin()
    display_node.destroy_node()
    rclpy.shutdown()


def main(args=None) -> None:
    # the image-queue is used to send images from the ros-node to the
    # gui-application. The value is either a 'RawImage', which
    # the ros-node requests do be shown, or alternatively 'None', in
    # order to indicate that nothing should be shown (i.e. the gui-window
    # is closed)
    image_queue: Queue[RawImage | None] = Queue(maxsize=1)
    # run hui-application and ros in two separate threads
    Thread(daemon=True, target=run_display_node, args=(image_queue,)).start()
    run_gui_application(image_queue)


if __name__ == "__main__":
    main()
