#!/usr/bin/python3
import base64
import json
import os
import time

import cv2
import depthai as dai
import numpy as np
import rclpy
from datatypes.srv import GetCameraImage
from rclpy.node import Node
from std_msgs.msg import String, Float64, Int32, Int32MultiArray

# --- On-device NN pose detection (EXPERIMENTELL) -----------------------------
# MoveNet (single pose, lightning) laeuft direkt auf der Myriad-X-VPU der
# OAK-D Lite und liefert 17 Koerper-Keypoints; ein Hand-Landmark-Netz
# (MediaPipe lite) bekommt vom Host einen Ausschnitt um das Handgelenk und
# liefert 21 Hand-Punkte fuer "Hand auf/zu". Die Ergebnisse werden im selben
# JSON-Format wie die Browser-MediaPipe-Erkennung auf browser_pose_landmarks
# publiziert - gesture_control funktioniert damit unveraendert. Nur aktiv,
# wenn ueber oak_nn_control "start" gesendet wurde (Motion-Capture-Seite,
# Quelle "Roboter-Kamera (NN)"). Blobs werden im Dockerfile heruntergeladen;
# fehlen sie oder schlaegt der Pipeline-Start fehl, laeuft die Kamera wie
# bisher ohne NN weiter (Fallback, siehe init_pipeline).
MOVENET_BLOB = os.getenv("OAK_MOVENET_BLOB", "/models/movenet.blob")
HAND_BLOB = os.getenv("OAK_HAND_BLOB", "/models/hand_landmark_lite.blob")
MOVENET_INPUT_SIZE = 192  # lightning variant
HAND_INPUT_SIZE = 224
# MoveNet keypoint order (fixed by the model) - names match what
# browser-pose-tracker.service.ts publishes, so retargeting.py just works.
MOVENET_KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
# minimum MoveNet score to include a keypoint in the payload (MoveNet scores
# run lower than MediaPipe visibility; consumers gate again at 0.5)
MOVENET_MIN_SCORE = 0.3
# hand landmark indices -> names, same subset the browser sends
HAND_KP_NAMES = {
    0: "wrist", 2: "thumb_mcp", 4: "thumb_tip",
    5: "index_mcp", 8: "index_tip", 9: "middle_mcp", 12: "middle_tip",
    13: "ring_mcp", 16: "ring_tip", 17: "pinky_mcp", 20: "pinky_tip",
}
HAND_SCORE_THRESHOLD = 0.5
# cached hand result is reused for this long before being dropped (each tick
# only ONE hand is inferred, alternating sides -> ~5 Hz per side at 10 Hz)
HAND_RESULT_MAX_AGE_S = 1.0

# --- Stereo-Tiefe fuer die Bewegungserfassung -------------------------------
# Die OAK-D Lite berechnet on-device (dedizierter Stereo-Block, KEIN NN) ein
# Tiefenbild, ausgerichtet auf die RGB-Sicht. Es wird stark verkleinert
# (DEPTH_MAP_W x DEPTH_MAP_H, uint16 Millimeter) als base64-JSON auf
# "depth_map" publiziert. gesture_control ersetzt damit die von MediaPipe nur
# GESCHAETZTE Tiefe der Browser-Landmarks durch echte Messwerte - dadurch
# werden Armdrehung und Ellbogenwinkel geometrisch korrekt. Nur aktiv,
# waehrend die Motion-Capture-Seite laeuft (oak_depth_control "start"/"stop",
# Pipeline wird dann neu aufgebaut) - haelt den Dauer-Stromverbrauch klein,
# die USB-Stromschiene dieses Pi ist knapp (over-current-Historie in dmesg).
DEPTH_MAP_W = 160
DEPTH_MAP_H = 90

# Selbstheilung: die OAK-D-Lite-Firmware kann mit beiden NNs abstuerzen
# ("Fatal error on MSS CPU", im ersten Live-Test einmal beobachtet). Der
# Retry-Wrapper (spin_camera) startet den Node dann neu - passiert das
# innerhalb dieses Fensters erneut, wird pro Absturz eine NN-Stufe
# abgeschaltet (beide NNs -> nur MoveNet -> ganz ohne NN), damit die
# normale Kamera nie dauerhaft mit abstuerzt.
_CRASH_WINDOW_S = 120.0
_recent_node_starts: list = []


def _nn_degrade_level() -> int:
    """0 = beide NNs, 1 = nur MoveNet, >=2 = kein NN."""
    now = time.monotonic()
    while _recent_node_starts and now - _recent_node_starts[0] > _CRASH_WINDOW_S:
        _recent_node_starts.pop(0)
    level = len(_recent_node_starts)
    _recent_node_starts.append(now)
    return level


class ErrorPublisher(Node):

    # def __new__(cls, error_message):
    #    print("creating new ErrorPublisher with Error message" + error_message)

    def __init__(self):
        super().__init__("error_publisher")
        self.publisher_ = self.create_publisher(String, "camera_topic", 10)
        timer_period = 1  # seconds
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.current_image = ""

    def timer_callback(self):
        msg = String()
        msg.data = "Camera not available: "
        self.publisher_.publish(msg)
        # self.get_logger().info('Publishing: "%s"' % msg.data)


class CameraNode(Node):

    def __init__(self):
        super().__init__("camera_node")
        self.publisher_ = self.create_publisher(String, "camera_topic", 10)
        self.timer_subscription = self.create_subscription(
            Float64, "timer_period_topic", self.timer_period_callback, 10
        )
        self.quality_factor_subscription = self.create_subscription(
            Int32, "quality_factor_topic", self.quality_factor_callback, 10
        )
        self.preview_size_subscription = self.create_subscription(
            Int32MultiArray, "size_topic", self.preview_size_callback, 10
        )

        # --- experimental on-device NN pose detection (see module header) ---
        self.nn_wanted = os.path.exists(MOVENET_BLOB)
        self.nn_available = False  # set by init_pipeline
        self.nn_active = False  # toggled via oak_nn_control
        self.movenet_queue = None
        self.hand_in_queue = None
        self.hand_out_queue = None
        self._hand_side_toggle = "left"
        self._pending_hand_side = None
        # {"left"/"right": (timestamp, {name: [x, y, z]})} in frame-normalized
        # coords, already aspect-scaled for the payload
        self._hand_results = {}
        self.oak_nn_control_subscription = self.create_subscription(
            String, "oak_nn_control", self.oak_nn_control_callback, 10
        )
        self.landmarks_publisher = self.create_publisher(
            String, "browser_pose_landmarks", 10
        )

        # --- Stereo-Tiefe (siehe Modul-Kommentar bei DEPTH_MAP_W) ---
        self.depth_requested = False  # toggled via oak_depth_control
        self.depth_queue = None
        self.oak_depth_control_subscription = self.create_subscription(
            String, "oak_depth_control", self.oak_depth_control_callback, 10
        )
        self.depth_publisher = self.create_publisher(String, "depth_map", 10)

        # Crash-Degradierungs-Level EINMAL pro Node-Konstruktion bestimmen
        # (spin_camera konstruiert nach einem Absturz neu) - NICHT pro
        # init_pipeline-Aufruf, denn die Steuer-Topics bauen die Pipeline
        # auch im Normalbetrieb um (Tiefe/NN an/aus), das sind keine Crashes.
        self.crash_level = _nn_degrade_level()

        # Initialize default preview size and quality factor
        self.preview_width = 1280
        self.preview_height = 720
        self.quality_factor = 80

        # Initialize pipeline when camera is available
        self.camera_available = self.init_pipeline()

        if self.camera_available:
            self.get_camera_image_service = self.create_service(
                GetCameraImage, "get_camera_image", self.get_camera_image_callback
            )
            self.get_logger().info("Camera service initialized.")
        else:
            self.get_logger().error("Camera not available.")

        self.timer_period = 0.1  # seconds
        self.timer = self.create_timer(self.timer_period, self.timer_callback)

    def get_camera_image_callback(self, request, response):
        self.get_logger().info(f"LEN IMAGE: {len(self.current_image)}")
        response.image_base64 = self.current_image
        return response

    def _build_pipeline(
        self, with_movenet: bool, with_hand: bool, with_depth: bool
    ) -> "dai.Pipeline":
        pipeline = dai.Pipeline()

        # Define a source - color camera
        camRgb = pipeline.createColorCamera()
        camRgb.setPreviewSize(self.preview_width, self.preview_height)
        camRgb.setInterleaved(False)

        # Create output
        xoutRgb = pipeline.createXLinkOut()
        xoutRgb.setStreamName("rgb")
        camRgb.preview.link(xoutRgb.input)

        if with_depth:
            # Stereo-Tiefe on-device (dedizierter Hardware-Block, kein NN):
            # beide Mono-Kameras -> StereoDepth, ausgerichtet auf die
            # RGB-Sicht (CAM_A), Ausgabegroesse 16:9 wie der RGB-Preview,
            # damit normalisierte Landmark-Koordinaten direkt aufs
            # Tiefenbild uebertragbar sind.
            monoLeft = pipeline.createMonoCamera()
            monoLeft.setResolution(
                dai.MonoCameraProperties.SensorResolution.THE_400_P
            )
            monoLeft.setBoardSocket(dai.CameraBoardSocket.CAM_B)
            monoRight = pipeline.createMonoCamera()
            monoRight.setResolution(
                dai.MonoCameraProperties.SensorResolution.THE_400_P
            )
            monoRight.setBoardSocket(dai.CameraBoardSocket.CAM_C)
            # 10 fps statt Default 30: der Host tickt ohnehin nur mit 10 Hz,
            # und weniger Stereo-Last auf der VPU haelt den RGB-Stream
            # fluessig (Latenz) und den Stromverbrauch klein.
            monoLeft.setFps(10)
            monoRight.setFps(10)

            stereoDepth = pipeline.createStereoDepth()
            stereoDepth.setDefaultProfilePreset(
                dai.node.StereoDepth.PresetMode.HIGH_DENSITY
            )
            stereoDepth.initialConfig.setMedianFilter(
                dai.MedianFilter.KERNEL_7x7
            )
            stereoDepth.setLeftRightCheck(True)
            stereoDepth.setDepthAlign(dai.CameraBoardSocket.CAM_A)
            stereoDepth.setOutputSize(640, 360)
            monoLeft.out.link(stereoDepth.left)
            monoRight.out.link(stereoDepth.right)
            xoutDepth = pipeline.createXLinkOut()
            xoutDepth.setStreamName("depth")
            stereoDepth.depth.link(xoutDepth.input)

        if with_movenet:
            # MoveNet: preview -> squash-resize to 192x192 -> NN -> host.
            # Squashing (no letterbox) keeps the normalized keypoint coords
            # directly mappable onto the full preview frame.
            manip = pipeline.createImageManip()
            manip.initialConfig.setResize(MOVENET_INPUT_SIZE, MOVENET_INPUT_SIZE)
            manip.initialConfig.setKeepAspectRatio(False)
            manip.initialConfig.setFrameType(dai.RawImgFrame.Type.RGB888p)
            manip.setMaxOutputFrameSize(
                MOVENET_INPUT_SIZE * MOVENET_INPUT_SIZE * 3
            )
            camRgb.preview.link(manip.inputImage)

            movenet = pipeline.createNeuralNetwork()
            movenet.setBlobPath(MOVENET_BLOB)
            # 1 Inferenz-Thread statt Default 2: mit 2 Threads pro NN (also
            # 4 bei beiden NNs) crashte die OAK-D-Lite-Firmware reproduzierbar
            # ("Fatal error on MSS CPU"); fuer die 10-Hz-Rate reicht 1 Thread.
            movenet.setNumInferenceThreads(1)
            manip.out.link(movenet.input)
            xoutMovenet = pipeline.createXLinkOut()
            xoutMovenet.setStreamName("movenet")
            movenet.out.link(xoutMovenet.input)

        # Hand landmarks: host crops a square around a wrist keypoint,
        # sends it in via XLinkIn, NN result comes back on hand_out.
        if with_hand:
            xinHand = pipeline.createXLinkIn()
            xinHand.setStreamName("hand_in")
            handNn = pipeline.createNeuralNetwork()
            handNn.setBlobPath(HAND_BLOB)
            handNn.setNumInferenceThreads(1)  # siehe Kommentar bei movenet
            xinHand.out.link(handNn.input)
            xoutHand = pipeline.createXLinkOut()
            xoutHand.setStreamName("hand_out")
            handNn.out.link(xoutHand.input)

        return pipeline

    def init_pipeline(self) -> bool:
        # Die Pipeline enthaelt NUR, was gerade wirklich gebraucht wird:
        # plain Kamera im Normalbetrieb (stabil, minimaler Stromverbrauch),
        # + Stereo-Tiefe waehrend Motion Capture (oak_depth_control),
        # + NNs nur im experimentellen NN-Modus (oak_nn_control).
        # Degradierungs-Reihenfolge bei Fehlern/Crashes: erst Hand-NN weg,
        # dann MoveNet, dann Tiefe, zuletzt plain - die normale Kamera darf
        # nie dauerhaft mit ausfallen.
        want_nn = self.nn_active and self.nn_wanted
        want_hand = want_nn and os.path.exists(HAND_BLOB)
        want_depth = self.depth_requested
        attempts = []
        for combo in [
            (want_nn, want_hand, want_depth),
            (want_nn, False, want_depth),
            (False, False, want_depth),
            (False, False, False),
        ]:
            if combo not in attempts:
                attempts.append(combo)

        if self.crash_level > 0:
            self.get_logger().warn(
                "recent camera restart(s) detected - degrading start level "
                f"to {self.crash_level}"
            )
            attempts = attempts[min(self.crash_level, len(attempts) - 1):]

        for with_movenet, with_hand, with_depth in attempts:
            try:
                self.pipeline = self._build_pipeline(
                    with_movenet, with_hand, with_depth
                )
                self.device = dai.Device(self.pipeline)
                self.queue = self.device.getOutputQueue(
                    name="rgb", maxSize=4, blocking=False
                )
                self.movenet_queue = (
                    self.device.getOutputQueue(name="movenet", maxSize=1, blocking=False)
                    if with_movenet
                    else None
                )
                self.hand_in_queue = (
                    self.device.getInputQueue(name="hand_in", maxSize=1, blocking=False)
                    if with_hand
                    else None
                )
                self.hand_out_queue = (
                    self.device.getOutputQueue(name="hand_out", maxSize=1, blocking=False)
                    if with_hand
                    else None
                )
                self.depth_queue = (
                    self.device.getOutputQueue(name="depth", maxSize=1, blocking=False)
                    if with_depth
                    else None
                )
                self.nn_available = with_movenet
                self.get_logger().info(
                    "Camera pipeline started "
                    f"(movenet={'on' if with_movenet else 'off'}, "
                    f"hand={'on' if with_hand else 'off'}, "
                    f"depth={'on' if with_depth else 'off'})."
                )
                return True
            except Exception as e:
                self.get_logger().error(
                    f"Camera pipeline start failed (movenet={with_movenet}, "
                    f"hand={with_hand}, depth={with_depth}): {e}"
                )
        self.device = None
        self.queue = None
        self.movenet_queue = None
        self.hand_in_queue = None
        self.hand_out_queue = None
        self.depth_queue = None
        self.nn_available = False
        return False

    def _rebuild_device(self):
        """Baut das Geraet mit der aktuell angeforderten Pipeline neu auf
        (Tiefe/NN an- oder abgeschaltet). Kurze Kamera-Unterbrechung (~2s),
        gleicher Mechanismus wie preview_size_callback."""
        try:
            if self.device:
                self.device.close()
        except Exception:
            pass
        self.camera_available = self.init_pipeline()

    def oak_nn_control_callback(self, msg: String):
        """Frontend toggles NN landmark publishing ("start"/"stop") when the
        motion-capture page uses the 'Roboter-Kamera (NN)' source. Die
        NN-Knoten sind nur waehrenddessen in der Pipeline (Strom/Stabilitaet)."""
        active = msg.data.strip().lower() == "start"
        if active == self.nn_active:
            return
        self.nn_active = active
        self.get_logger().info(f"oak_nn_control: active={self.nn_active}")
        self._rebuild_device()

    def oak_depth_control_callback(self, msg: String):
        """Motion-Capture-Seite aktiv -> Stereo-Tiefe mitlaufen lassen
        (siehe Modul-Kommentar bei DEPTH_MAP_W)."""
        requested = msg.data.strip().lower() == "start"
        if requested == self.depth_requested:
            return
        self.depth_requested = requested
        self.get_logger().info(
            f"oak_depth_control: requested={self.depth_requested}"
        )
        self._rebuild_device()

    def timer_callback(self):
        if not self.queue:
            return
        image_rgb = self.queue.tryGet()  # non-blocking call
        if image_rgb is None:
            return
        # data is originally represented as a flat 1D array, it needs to be converted into HxWxC form
        frame = image_rgb.getCvFrame()

        # Convert the image to base64
        retval, buffer = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality_factor]
        )
        jpg_as_text = base64.b64encode(buffer)

        msg = String()
        msg.data = jpg_as_text.decode("utf-8")  # convert bytes to string
        self.current_image = msg.data
        self.publisher_.publish(msg)

        if self.depth_queue is not None:
            try:
                self._publish_depth_map()
            except Exception as e:
                self.get_logger().error(f"depth map publishing failed: {e}")

        if self.nn_active and self.nn_available:
            try:
                self._process_nn(frame)
            except Exception as e:
                self.get_logger().error(f"NN processing failed: {e}")

    def _publish_depth_map(self):
        """Neuestes Tiefenbild stark verkleinert publizieren (uint16 mm,
        little-endian, base64) - klein genug fuer 10 Hz ueber lokales DDS."""
        packet = None
        while True:  # drain to the newest frame
            candidate = self.depth_queue.tryGet()
            if candidate is None:
                break
            packet = candidate
        if packet is None:
            return
        depth = packet.getFrame()  # uint16, mm
        small = cv2.resize(
            depth, (DEPTH_MAP_W, DEPTH_MAP_H), interpolation=cv2.INTER_NEAREST
        )
        out = String()
        out.data = json.dumps({
            "w": DEPTH_MAP_W,
            "h": DEPTH_MAP_H,
            "data": base64.b64encode(
                np.ascontiguousarray(small, dtype="<u2").tobytes()
            ).decode("ascii"),
        })
        self.depth_publisher.publish(out)

    # --- on-device NN processing (see module header) ---------------------

    def _process_nn(self, frame):
        h, w = frame.shape[:2]
        aspect = w / h if h > 0 else 16 / 9

        keypoints = self._decode_movenet()
        pose_payload = {}
        keypoints_px = {}
        if keypoints is not None:
            for name, (ky, kx, score) in keypoints.items():
                keypoints_px[name] = (kx * w, ky * h, score)
                if score >= MOVENET_MIN_SCORE:
                    # same format as browser-pose-tracker.service.ts:
                    # [x*aspect, y, score, z*aspect]; MoveNet has no z.
                    pose_payload[name] = [kx * aspect, ky, float(score), 0.0]

        self._collect_hand_result(w, h, aspect)
        self._request_next_hand_crop(frame, keypoints_px, w, h)

        now = time.monotonic()
        hands_payload = {
            side: points
            for side, (ts, points) in self._hand_results.items()
            if now - ts <= HAND_RESULT_MAX_AGE_S
        }

        out = String()
        out.data = json.dumps({"pose": pose_payload, "hands": hands_payload})
        self.landmarks_publisher.publish(out)

    def _decode_movenet(self):
        """Latest MoveNet result -> {name: (y, x, score)} normalized, or None."""
        if self.movenet_queue is None:
            return None
        result = None
        while True:  # drain to the newest result
            packet = self.movenet_queue.tryGet()
            if packet is None:
                break
            result = packet
        if result is None:
            return None
        values = np.array(result.getLayerFp16("Identity")).reshape(-1, 3)
        return {
            name: (float(values[i][0]), float(values[i][1]), float(values[i][2]))
            for i, name in enumerate(MOVENET_KEYPOINT_NAMES)
            if i < len(values)
        }

    def _request_next_hand_crop(self, frame, keypoints_px, w, h):
        """Crops a square around one wrist (alternating sides each tick) and
        feeds it to the on-device hand landmark NN. The crop box is centered
        slightly beyond the wrist (hands extend past it) and sized relative
        to the forearm length, so it scales with distance to the camera."""
        if self.hand_in_queue is None:
            return
        side = self._hand_side_toggle
        self._hand_side_toggle = "right" if side == "left" else "left"

        wrist = keypoints_px.get(f"{side}_wrist")
        elbow = keypoints_px.get(f"{side}_elbow")
        if not wrist or not elbow or wrist[2] < MOVENET_MIN_SCORE:
            self._pending_hand_side = None
            return
        wx, wy, _ = wrist
        ex, ey, _ = elbow
        forearm = max(((wx - ex) ** 2 + (wy - ey) ** 2) ** 0.5, 1.0)
        cx = wx + 0.35 * (wx - ex)
        cy = wy + 0.35 * (wy - ey)
        half = max(1.1 * forearm, 48.0)

        x0 = int(max(0, min(cx - half, w - 2)))
        y0 = int(max(0, min(cy - half, h - 2)))
        x1 = int(max(x0 + 2, min(cx + half, w)))
        y1 = int(max(y0 + 2, min(cy + half, h)))
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            self._pending_hand_side = None
            return

        resized = cv2.resize(crop, (HAND_INPUT_SIZE, HAND_INPUT_SIZE))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        img = dai.ImgFrame()
        img.setType(dai.RawImgFrame.Type.RGB888p)
        img.setWidth(HAND_INPUT_SIZE)
        img.setHeight(HAND_INPUT_SIZE)
        img.setData(rgb.transpose(2, 0, 1).flatten())
        self.hand_in_queue.send(img)
        # remembered so the async result (next tick) maps back correctly
        self._pending_hand_side = (side, x0, y0, x1 - x0, y1 - y0)

    def _collect_hand_result(self, w, h, aspect):
        """Reads the hand NN result of the crop sent LAST tick (async by one
        tick) and stores frame-normalized, aspect-scaled hand points."""
        if self.hand_out_queue is None or self._pending_hand_side is None:
            return
        packet = self.hand_out_queue.tryGet()
        if packet is None:
            return
        side, x0, y0, cw, ch = self._pending_hand_side
        try:
            score = packet.getLayerFp16("Identity_1")[0]
            raw = np.array(
                packet.getLayerFp16("Identity_dense/BiasAdd/Add")
            ).reshape(-1, 3)
        except Exception:
            self.get_logger().warn(
                f"unexpected hand NN layers: {packet.getAllLayerNames()}"
            )
            return
        if score < HAND_SCORE_THRESHOLD:
            self._hand_results.pop(side, None)
            return
        points = {}
        for index, name in HAND_KP_NAMES.items():
            if index >= len(raw):
                continue
            lx, ly, lz = raw[index] / HAND_INPUT_SIZE
            fx = (x0 + lx * cw) / w
            fy = (y0 + ly * ch) / h
            fz = lz * cw / w
            points[name] = [fx * aspect, fy, fz * aspect]
        self._hand_results[side] = (time.monotonic(), points)

    def timer_period_callback(self, msg):
        self.timer_period = msg.data
        self.timer.cancel()  # cancel the old timer
        self.timer = self.create_timer(
            self.timer_period, self.timer_callback
        )  # create a new timer with updated period

    def quality_factor_callback(self, msg):
        self.quality_factor = msg.data

    def preview_size_callback(self, msg):
        self.preview_width, self.preview_height = msg.data

        # Reset pipeline with new preview size
        self._rebuild_device()


def spin_camera(times):
    cnt = times
    if cnt == 0:
        print(
            "Couldn't restart camera due to displayed error/s, publishing error message"
        )
        rclpy.spin(error_publisher)
    else:
        try:
            camera_node = CameraNode()
            rclpy.spin(camera_node)
        except Exception as exc:
            error_publisher.timer_callback()
            print(exc)
        finally:
            if "camera_node" in locals():
                camera_node.destroy_node()
                print("camera_node destroyed")
            cnt = times - 1
            print("Retry starting camera..." + str(cnt))
            spin_camera(cnt)
    return


def main(args=None):
    rclpy.init()
    global error_publisher
    error_publisher = ErrorPublisher()
    print("Starting camera")
    # 6 statt 3: die NN-Degradierung (siehe _nn_degrade_level) verbraucht
    # bei einem instabilen NN-Start bis zu 2 Versuche allein fuers
    # Herunterstufen (beide NNs -> nur MoveNet -> kein NN) - mit nur 3
    # Versuchen waere fuer echte voruebergehende Kamera-Aussetzer (z.B.
    # USB-Wackler) danach kein Retry mehr uebrig.
    spin_camera(6)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
