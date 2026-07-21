# audio_loop.py
#
# Gemini live audio loop that:
# - Subscribes to a ROS audio topic and forwards PCM chunks to Gemini live session.
# - Receives audio (TTS) and transcript events back from Gemini.
# - Streams user/assistant transcripts into ChatNode via the CreateOrUpdateChatMessage srv
#   so the chat UI updates live while Gemini speaks.
# - Handles Stop/Start robustly by closing the live session and joining the worker thread.

import asyncio
import base64
import os
import logging
import threading
from typing import Any, Optional

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import Int16MultiArray
from pib_api_client import voice_assistant_client, pose_client

import pyaudio
from google import genai
from google.genai import types as genai_types

import wave
from pathlib import Path
from datetime import datetime
from asyncio import QueueEmpty

# service API to ChatNode (to avoid duplicating DB/publish logic here)
from datatypes.srv import CreateOrUpdateChatMessage
# camera stills, only polled when personality.camera_access_enabled is True
from datatypes.srv import GetCameraImage
# move_joint tool call, only usable when personality.movement_access_enabled
# is True - reuses the same ApplyJointTrajectory service the joint-control
# UI and Blockly programs already go through, so the existing
# rotation_range_min/max safety clamp (Motor._validate_position) applies
# here too with no extra code.
from datatypes.srv import ApplyJointTrajectory
# show_emotion tool - publishes the same display_image topic the Pose page's
# emotion buttons and Blockly's set_eyes_emotion block use.
from datatypes.msg import DisplayImage, ImageId, ImageFormat
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

import queue
import time

# ——— Logging ———
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("GeminiAudioLoop")

# ——— Model + audio IO constants ———
pya = pyaudio.PyAudio()
FORMAT = pyaudio.paInt16
CHANNELS = 1  # send mono to Gemini
SEND_SAMPLE_RATE = 16000  # recorder publishes 16 kHz mono
RECEIVE_SAMPLE_RATE = 24000  # model replies at 24 kHz
CHUNK_SIZE = 1024

MODEL = "gemini-2.5-flash-native-audio-preview-09-2025"
CONFIG = {
    "response_modalities": ["AUDIO"],  # request synthesized speech back
    "input_audio_transcription": {},  # get user (input) transcript stream
    "output_audio_transcription": {},  # get assistant (output) transcript stream
}
# All motor names pib ships with (see pib_api_client.motor_client / the
# "Alle Gelenke" page) - kept as a plain list here (rather than fetched at
# runtime) so the tool's enum is available immediately at connect time.
MOTOR_NAMES = [
    "turn_head_motor",
    "tilt_forward_motor",
    "upper_arm_left_rotation",
    "elbow_left",
    "lower_arm_left_rotation",
    "shoulder_vertical_left",
    "shoulder_horizontal_left",
    "upper_arm_right_rotation",
    "elbow_right",
    "lower_arm_right_rotation",
    "shoulder_vertical_right",
    "shoulder_horizontal_right",
    "thumb_right_opposition",
    "thumb_right_stretch",
    "index_right_stretch",
    "middle_right_stretch",
    "ring_right_stretch",
    "pinky_right_stretch",
    "thumb_left_opposition",
    "thumb_left_stretch",
    "index_left_stretch",
    "middle_left_stretch",
    "ring_left_stretch",
    "pinky_left_stretch",
    "wrist_left",
    "wrist_right",
]

# Human-readable (German) description per motor - injected as plain text
# into the system_instruction (see run()) so the model can actually name
# joints correctly when talking to the user and pick the right one for a
# request like "heb den Arm", rather than only ever seeing the raw
# identifiers buried in the move_joint tool schema's enum, which it tends
# to paraphrase incorrectly.
MOTOR_NAME_DESCRIPTIONS = """\
- turn_head_motor: Kopf drehen (links/rechts)
- tilt_forward_motor: Kopf nach vorne neigen
- shoulder_vertical_left / shoulder_vertical_right: linke/rechte Schulter \
heben und senken (Arm seitlich nach oben/unten) - das ist der Hauptmotor \
zum "Arm heben"
- shoulder_horizontal_left / shoulder_horizontal_right: linke/rechte \
Schulter nach vorne/hinten schwenken
- upper_arm_left_rotation / upper_arm_right_rotation: linken/rechten \
Oberarm um seine eigene Achse drehen
- elbow_left / elbow_right: linken/rechten Ellbogen beugen/strecken
- lower_arm_left_rotation / lower_arm_right_rotation: linken/rechten \
Unterarm um seine eigene Achse drehen
- wrist_left / wrist_right: linkes/rechtes Handgelenk drehen
- thumb_left_opposition / thumb_right_opposition: linken/rechten Daumen \
zur Hand hin/weg bewegen
- thumb_left_stretch / thumb_right_stretch: linken/rechten Daumen \
strecken/beugen
- index_left_stretch / index_right_stretch: linken/rechten Zeigefinger \
strecken/beugen
- middle_left_stretch / middle_right_stretch: linken/rechten Mittelfinger \
strecken/beugen
- ring_left_stretch / ring_right_stretch: linken/rechten Ringfinger \
strecken/beugen
- pinky_left_stretch / pinky_right_stretch: linken/rechten kleinen Finger \
strecken/beugen\
"""

# Gemini Live function-calling tools: let the model actually move pib's
# motors (only added to the session config when the active personality has
# movement_access_enabled).
#
# "position" is in DEGREES (matching the same rotation_range_min/max unit
# every motor is configured in, just /100 for a human/AI-friendly number -
# the ROS side stores hundredths of a degree). An earlier version described
# this as "-100 to 100 percent", which the model dutifully used, sending
# values like 50 - but Motor._validate_position() clamps against the RAW
# hundredths-of-a-degree range (e.g. -9000..9000), so a "position=50" call
# only ever moved a joint by half a degree: technically successful,
# practically imperceptible ("reacts poorly or not at all"). Values outside
# a joint's configured range are still clamped automatically server-side,
# so this can never move a joint past its limit - just no longer silently
# 100x too small.
MOVE_JOINT_TOOL = {
    "function_declarations": [
        {
            "name": "move_joint",
            "description": (
                "Bewegt ein einzelnes Gelenk (Motor) von pib auf eine neue "
                "Position. position ist der Zielwinkel in GRAD (nicht "
                "Prozent!), typischer Bereich je nach Gelenk etwa -90 bis "
                "90 (0 ist meist die Mittelstellung); Werte ausserhalb des "
                "erlaubten Bereichs werden automatisch auf die Grenze "
                "begrenzt. Fuer eine sichtbare Bewegung reichen kleine "
                "Aenderungen oft schon nicht aus - im Zweifel eher grosszuegige "
                "Winkeldifferenzen verwenden (z.B. 30-60 Grad), nicht nur "
                "wenige Grad."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "motor_name": {
                        "type": "STRING",
                        "enum": MOTOR_NAMES,
                        "description": "Name des zu bewegenden Motors.",
                    },
                    "position": {
                        "type": "INTEGER",
                        "description": "Zielwinkel in Grad (nicht Prozent).",
                    },
                },
                "required": ["motor_name", "position"],
            },
        },
        {
            "name": "reset_pose",
            "description": (
                "Bewegt ALLE Gelenke zurueck in die neutrale Ausgangs-/"
                "Ruheposition (dieselbe Pose wie beim Hochfahren). Danach "
                "rufen, wenn eine gezeigte Bewegung/Geste abgeschlossen ist, "
                "damit pib nicht in einer verdrehten Haltung stehen bleibt."
            ),
            "parameters": {"type": "OBJECT", "properties": {}},
        },
    ]
}

# Fixed emotions shown on pib's display (see pose.component.ts's emotions
# list / display-block.ts's getEmotions - kept in sync manually, "HEART" was
# removed there too). Deliberately does NOT include user-uploaded custom
# facial expressions - those have per-install names/ids the model has no
# stable way to know about ahead of time.
EMOTION_NAME_TO_IMAGE_ID = {
    "neutral": ImageId.PIB_EYES_ANIMATED,
    "happy": ImageId.PIB_EYES_HAPPY,
    "sad": ImageId.PIB_EYES_SAD,
    "angry": ImageId.PIB_EYES_ANGRY,
    "surprised": ImageId.PIB_EYES_SURPRISED,
    "sleepy": ImageId.PIB_EYES_SLEEPY,
    "star": ImageId.PIB_EYES_STAR,
    "cool": ImageId.PIB_EYES_COOL,
    "wink": ImageId.PIB_EYES_WINK,
}

# Gemini Live function-calling tool: lets the model show a facial expression
# on pib's display matching the mood of the conversation (only added when
# the active personality has emotion_access_enabled - independent of
# movement_access_enabled).
SHOW_EMOTION_TOOL = {
    "function_declarations": [
        {
            "name": "show_emotion",
            "description": (
                "Zeigt einen Gesichtsausdruck auf pibs Display, passend zur "
                "Stimmung des Gespraechs (z.B. 'happy' wenn du dich freust, "
                "'surprised' bei einer ueberraschenden Wendung). 'neutral' "
                "setzt die normalen, ruhigen Augen zurueck."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "emotion": {
                        "type": "STRING",
                        "enum": list(EMOTION_NAME_TO_IMAGE_ID.keys()),
                        "description": "Welcher Gesichtsausdruck gezeigt werden soll.",
                    },
                },
                "required": ["emotion"],
            },
        }
    ]
}

ROS_AUDIO_TOPIC = os.getenv("ROS_AUDIO_TOPIC", "audio_stream")
# how often (seconds) a camera still is polled and sent to Gemini as video
# input, when the active personality has camera_access_enabled - Gemini Live
# needs far less than the camera's native ~10 FPS for scene understanding.
GEMINI_VIDEO_INTERVAL_S = float(os.getenv("GEMINI_VIDEO_INTERVAL_S", "2.0"))


# ——— Live session lifetime management ———
# Live API limits:
# - Without compression, audio-only sessions are limited to ~15 minutes.
# - A single WebSocket connection is limited to ~10 minutes (GoAway warning before termination).
# Enable BOTH:
#   * context window compression -> removes the session duration cap
#   * session resumption + reconnect -> survives the connection cap
ENABLE_CONTEXT_COMPRESSION = os.getenv("ENABLE_CONTEXT_COMPRESSION", "1") == "1"
ENABLE_SESSION_RESUMPTION = os.getenv("ENABLE_SESSION_RESUMPTION", "1") == "1"

# Reasonable defaults for native-audio 128k context models (tune if needed)
CWC_TRIGGER_TOKENS = int(os.getenv("CWC_TRIGGER_TOKENS", "100000"))
CWC_TARGET_TOKENS = int(os.getenv("CWC_TARGET_TOKENS", "80000"))

# Small delay before reconnecting (prevents tight loops on persistent failures)
LIVE_RECONNECT_BACKOFF_S = float(os.getenv("LIVE_RECONNECT_BACKOFF_S", "0.5"))

# pib's ReSpeaker 4 Mic Array (UAC1.0) has no onboard echo cancellation
# (unlike the 6-channel ReSpeaker v2.0 this pipeline's channel-selection was
# originally written for - see audio_streamer.py). Without it, the mic picks
# up pib's own TTS playback and Gemini's live API treats that as the user
# interrupting, so it cuts itself off mid-sentence. Dropping mic audio while
# (and briefly after) pib is speaking prevents that self-interruption; real
# barge-in (user interrupting pib) is intentionally sacrificed as the
# trade-off until real acoustic echo cancellation is set up.
MIC_MUTE_TRAIL_S = float(os.getenv("MIC_MUTE_TRAIL_S", "0.6"))


class ReconnectRequested(RuntimeError):
    """Raised by tasks to request a clean Live session reconnect."""

    pass


# ——————————————————————————————————————————
#         ROS subscriber bridge (thread)
# ——————————————————————————————————————————
class RosAudioBridge:
    """
    Subscribes to a ROS topic carrying PCM16 mono @16k (Int16MultiArray or AudioData)
    and forwards chunks into an asyncio.Queue that send_realtime() consumes.
    Runs in its own thread with a SingleThreadedExecutor.
    """

    def __init__(
        self, topic: str, loop: asyncio.AbstractEventLoop, out_queue: asyncio.Queue
    ):
        self._topic = topic
        self._loop = loop
        self._out_queue = out_queue
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._started_evt = threading.Event()

    def start(self):
        """Start ROS subscriber thread and wait until it’s actually listening."""
        self._thread = threading.Thread(
            target=self._run, name="RosAudioBridge", daemon=True
        )
        self._thread.start()
        self._started_evt.wait(timeout=3.0)

    def stop(self):
        """Signal shutdown and join quickly (best-effort)."""
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _run(self):
        try:
            # Optional support for audio_common_msgs/AudioData (bytes)
            AudioData = None
            try:
                from audio_common_msgs.msg import AudioData as _AudioData  # type: ignore

                AudioData = _AudioData
            except Exception:
                pass

            # Ensure a ROS context exists in this thread
            if not rclpy.ok():
                rclpy.init()

            class _Node(Node):
                """Tiny ROS node that receives PCM and forwards to asyncio queue."""

                def __init__(self, topic, loop, queue, stop_evt):
                    super().__init__("ros_audio_bridge")
                    self._loop = loop
                    self._queue = queue
                    self._stop_evt = stop_evt
                    self._subs = []
                    self._subs.append(
                        self.create_subscription(
                            Int16MultiArray, topic, self._cb_int16, 10
                        )
                    )
                    if AudioData is not None:
                        self._subs.append(
                            self.create_subscription(
                                AudioData, topic, self._cb_bytes, 10
                            )
                        )
                    self.get_logger().info(
                        f"Subscribed to '{topic}' for PCM16 mono @16k"
                    )

                def _enqueue(self, payload: bytes):
                    """Push a PCM payload into the asyncio queue (thread-safe)."""
                    if self._stop_evt.is_set():
                        return

                    async def _put():
                        await self._queue.put(
                            {"data": payload, "mime_type": "audio/pcm"}
                        )

                    try:
                        fut = asyncio.run_coroutine_threadsafe(_put(), self._loop)
                        fut.result(timeout=0.25)
                    except Exception:
                        # If the loop is busy, drop late chunks rather than blocking.
                        pass

                def _cb_int16(self, msg: Int16MultiArray):
                    try:
                        arr = np.asarray(msg.data, dtype=np.int16)
                        self._enqueue(arr.tobytes())
                    except Exception as e:
                        self.get_logger().error(f"Int16MultiArray convert error: {e}")

                def _cb_bytes(self, msg):  # AudioData
                    try:
                        self._enqueue(bytes(msg.data))
                    except Exception as e:
                        self.get_logger().error(f"AudioData forward error: {e}")

            node = _Node(self._topic, self._loop, self._out_queue, self._stop_evt)
            self._started_evt.set()

            executor = SingleThreadedExecutor(context=rclpy.get_default_context())
            executor.add_node(node)
            while not self._stop_evt.is_set():
                executor.spin_once(timeout_sec=0.1)
            executor.shutdown()
            node.destroy_node()

        except Exception:
            logger.exception("RosAudioBridge crashed")


class RosCameraBridge:
    """
    Polls the get_camera_image service on an interval and forwards JPEG
    stills into an asyncio.Queue that send_video_frames() consumes.
    Runs in its own thread, using the same lazy-client + spin_until_future_complete
    pattern already used for the ChatNode service calls below.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        out_queue: asyncio.Queue,
        interval_s: float,
    ):
        self._loop = loop
        self._out_queue = out_queue
        self._interval_s = interval_s
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._node: Optional[Node] = None
        self._client = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name="RosCameraBridge", daemon=True
        )
        self._thread.start()

    def stop(self):
        """Signal shutdown and join quickly (best-effort)."""
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._node:
            try:
                self._node.destroy_node()
            except Exception:
                pass
            self._node = None

    def _enqueue(self, jpeg_bytes: bytes):
        """Push a JPEG frame into the asyncio queue (thread-safe), dropping
        a stale pending frame instead of blocking if send_video_frames is slow."""
        if self._stop_evt.is_set():
            return

        async def _put():
            if self._out_queue.full():
                try:
                    self._out_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await self._out_queue.put(
                {"data": jpeg_bytes, "mime_type": "image/jpeg"}
            )

        try:
            fut = asyncio.run_coroutine_threadsafe(_put(), self._loop)
            fut.result(timeout=0.5)
        except Exception:
            pass

    def _run(self):
        try:
            if not rclpy.ok():
                rclpy.init()
            self._node = Node("gemini_camera_bridge")
            self._client = self._node.create_client(
                GetCameraImage, "get_camera_image"
            )
            if not self._client.wait_for_service(timeout_sec=3.0):
                logger.warning(
                    "get_camera_image service not available yet; will keep retrying."
                )

            while not self._stop_evt.is_set():
                if self._client.service_is_ready():
                    try:
                        future = self._client.call_async(GetCameraImage.Request())
                        rclpy.spin_until_future_complete(
                            self._node, future, timeout_sec=1.0
                        )
                        if future.done() and future.result() is not None:
                            image_base64 = future.result().image_base64
                            if image_base64:
                                self._enqueue(base64.b64decode(image_base64))
                    except Exception:
                        logger.exception(
                            "RosCameraBridge: get_camera_image call failed"
                        )
                self._stop_evt.wait(self._interval_s)

        except Exception:
            logger.exception("RosCameraBridge crashed")


# Same value as pib_api/flask/default_pose_constants.py's STARTUP_POSE_NAME -
# duplicated here since this container doesn't have the Flask package
# available, just its HTTP client (pib_api_client.pose_client).
STARTUP_POSE_NAME = "Startup/Resting"


class RosMotorBridge:
    """Backs the move_joint/reset_pose Gemini function-calling tools: a
    small, lazily-started ROS node + client for the existing
    apply_joint_trajectory service (the same one the joint-control UI and
    Blockly programs use). Only instantiated when the active personality
    has movement_access_enabled.

    move_joint()/reset_pose() block on rclpy.spin_until_future_complete, so
    callers must run them off the asyncio event loop (see receive_audio's
    run_in_executor call) - same reasoning as RosCameraBridge, but here we
    call it on-demand per tool call rather than on a polling timer."""

    def __init__(self):
        self._node: Optional[Node] = None
        self._client = None
        self._lock = threading.Lock()

    def _ensure_started(self):
        with self._lock:
            if self._node is not None:
                return
            if not rclpy.ok():
                rclpy.init()
            self._node = Node("gemini_motor_bridge")
            self._client = self._node.create_client(
                ApplyJointTrajectory, "apply_joint_trajectory"
            )

    def _apply(self, joint_names: list[str], positions: list[float]) -> tuple[bool, str]:
        self._ensure_started()
        if not self._client.wait_for_service(timeout_sec=3.0):
            return False, "apply_joint_trajectory service not available"

        jt = JointTrajectory()
        jt.joint_names = joint_names
        jt.points = []
        for position in positions:
            point = JointTrajectoryPoint()
            point.positions = [position]
            jt.points.append(point)

        request = ApplyJointTrajectory.Request()
        request.joint_trajectory = jt
        try:
            future = self._client.call_async(request)
            with self._lock:
                rclpy.spin_until_future_complete(self._node, future, timeout_sec=5.0)
            if not future.done() or future.result() is None:
                return False, "timed out waiting for motor response"
            return bool(future.result().successful), ""
        except Exception as e:
            logger.exception("RosMotorBridge: apply_joint_trajectory call failed")
            return False, str(e)

    def move_joint(self, motor_name: str, degrees: int) -> tuple[bool, str]:
        """Returns (successful, error_message). degrees is converted to the
        hundredths-of-a-degree unit rotation_range_min/max (and thus
        ApplyJointTrajectory) actually use."""
        return self._apply([motor_name], [float(degrees) * 100])

    def reset_pose(self) -> tuple[bool, str]:
        """Moves every joint back to the Startup/Resting pose."""
        successful, motor_positions = pose_client.get_pose_by_name(STARTUP_POSE_NAME)
        if not successful or motor_positions is None:
            return False, f"could not find pose '{STARTUP_POSE_NAME}'"
        positions = motor_positions.get("motorPositions", [])
        if not positions:
            return False, f"pose '{STARTUP_POSE_NAME}' has no motor positions"
        joint_names = [p["motorName"] for p in positions]
        joint_positions = [float(p["position"]) for p in positions]
        return self._apply(joint_names, joint_positions)


class RosEmotionBridge:
    """Backs the show_emotion Gemini function-calling tool: a small,
    lazily-started ROS node + publisher for the display_image topic (the
    same one the Pose page's emotion buttons and Blockly's set_eyes_emotion
    block publish to). Only instantiated when the active personality has
    emotion_access_enabled."""

    def __init__(self):
        self._node: Optional[Node] = None
        self._publisher = None
        self._lock = threading.Lock()

    def _ensure_started(self):
        with self._lock:
            if self._node is not None:
                return
            if not rclpy.ok():
                rclpy.init()
            self._node = Node("gemini_emotion_bridge")
            self._publisher = self._node.create_publisher(
                DisplayImage, "display_image", 1
            )

    def show_emotion(self, image_id: int) -> tuple[bool, str]:
        """Returns (successful, error_message)."""
        self._ensure_started()
        try:
            message = DisplayImage()
            message.id = ImageId(value=image_id)
            message.format = ImageFormat(value=ImageFormat.ANIMATED_GIF)
            self._publisher.publish(message)
            return True, ""
        except Exception as e:
            logger.exception("RosEmotionBridge: show_emotion call failed")
            return False, str(e)


# ——————————————————————————————————————————
#                Main audio loop
# ——————————————————————————————————————————
class GeminiAudioLoop:
    """
    Background worker that:
      - Maintains a Gemini live audio session.
      - Sends ROS PCM input upstream; receives PCM out + transcripts downstream.
      - For each transcript slice (user or assistant), calls ChatNode service to
        create/update the message so the UI reflects text while audio is speaking.
      - Supports Stop/Start: Stop sets an event, attempts to close the live session,
        cancels all tasks, and joins the thread so a new run can start cleanly.
    """

    def __init__(self, api_key: str = "") -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_listening = False
        self._chat_id: Optional[str] = None

        # Initialized in run()
        self.audio_in_queue: asyncio.Queue[tuple[bytes, Optional[str]]]
        self.out_queue: asyncio.Queue[bytes]
        self.session = None  # gemini live session (aio client)
        self.playback_stream = None  # PyAudio output stream
        self.api_key = api_key

        # monotonic timestamp until which mic audio should be dropped rather
        # than sent upstream - see MIC_MUTE_TRAIL_S above. Kept extended by
        # play_audio() for as long as pib's own speech is still playing.
        self._mic_muted_until: float = 0.0

        # ROS bridge handle
        self._ros_bridge: Optional[RosAudioBridge] = None
        # Camera bridge handle (only started when the personality has
        # camera_access_enabled)
        self._camera_bridge: Optional[RosCameraBridge] = None
        # Motor bridge handle (only started when the personality has
        # movement_access_enabled) - backs the move_joint tool call.
        self._motor_bridge: Optional[RosMotorBridge] = None
        # Emotion bridge handle (only started when the personality has
        # emotion_access_enabled) - backs the show_emotion tool call.
        self._emotion_bridge: Optional[RosEmotionBridge] = None

        # Logging / turns (optional: write input/output wavs)
        self._turn_id = 0
        self._in_wav: Optional[wave.Wave_write] = None
        self._out_wav: Optional[wave.Wave_write] = None
        self._log_lock: Optional[asyncio.Lock] = None
        self._log_input_dir = Path(os.getenv("AUDIO_LOG_INPUT_DIR", "input"))
        self._log_output_dir = Path(os.getenv("AUDIO_LOG_OUTPUT_DIR", "output"))

        # Service client state (for streaming ChatMessages to ChatNode)
        self._srv_node: Optional[Node] = None
        self._srv_client = None
        self._accum_text: str = ""
        self._last_pib_message_id: str = ""
        self._current_role: Optional[str] = None  # "user" | "assistant" | None

        # Chat update worker (so DB/UI updates don't block audio)
        self._chat_queue: "queue.Queue[CreateOrUpdateChatMessage.Request]" = (
            queue.Queue(maxsize=32)
        )
        self._chat_worker: Optional[threading.Thread] = None
        self._last_srv_call_time: float = 0.0
        self._srv_call_min_interval: float = 0.15  # seconds, 150 ms default

        # Event loop reference (used by stop() to close session)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Live API session resumption handle (updated from SessionResumptionUpdate)
        self._session_handle: Optional[str] = None

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    # ---------- lifecycle ----------

    def start(self, chat_id) -> None:
        """
        Start the Gemini audio loop in a background thread.
        If already running, this is a no-op (defensive).
        """
        if self._is_listening:
            logger.info("GeminiAudioLoop is already running.")
            return

        self._chat_id = chat_id
        self._stop_event.clear()

        # Start chat worker first so it can consume requests
        self._start_chat_worker()

        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()
        self._is_listening = True
        logger.info("GeminiAudioLoop: started")

    def stop(self, join_timeout: float = 5.0) -> None:
        """
        Signal the loop to stop and join the thread.
        - Sets the stop flag.
        - Tries to close the live session (from this thread) via run_coroutine_threadsafe.
        - Joins the worker thread (best-effort) so Start can run cleanly after.
        """
        if not self._is_listening:
            logger.info("GeminiAudioLoop is not running.")
            return

        self._stop_event.set()
        # Wake chat worker so it can exit
        try:
            self._chat_queue.put_nowait(None)  # sentinel
        except Exception:
            pass

        if self._chat_worker:
            self._chat_worker.join(timeout=join_timeout)
            if self._chat_worker.is_alive():
                logger.warning("Chat worker thread did not stop cleanly.")
            else:
                self._chat_worker = None

        # Reset per-stream accumulators to avoid accidental reuse next run
        self._accum_text = ""
        self._last_pib_message_id = ""
        self._current_role = None

        # Try to close the live session from here (async -> thread-safe)
        if self._loop and self.session is not None:
            try:

                async def _close():
                    try:
                        await self.session.close()
                    except Exception:
                        pass

                asyncio.run_coroutine_threadsafe(_close(), self._loop)
            except Exception:
                pass

        if self._thread:
            self._thread.join(timeout=join_timeout)
            if self._thread.is_alive():
                logger.warning("GeminiAudioLoop thread did not stop cleanly.")
            else:
                self._thread = None

        self._is_listening = False
        logger.info("GeminiAudioLoop: stopped")

    def _run_thread(self):
        """
        Thread entrypoint: create an isolated asyncio loop and run self.run().
        This allows the main ROS process to remain responsive while we do async IO.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self.run())
        finally:
            self._loop = None
            loop.close()

    # ---------- small queue helpers ----------

    def _drain_queue(self, q: asyncio.Queue):
        """Best-effort drain to keep queues bounded during teardown."""
        drained = 0
        try:
            while True:
                q.get_nowait()
                drained += 1
        except QueueEmpty:
            if drained:
                logger.debug("Drained %d items from queue.", drained)

    async def _flush_queues(self, where: str):
        """Drain known queues on shutdown to free memory quickly."""
        logger.debug("Queues flushed (%s).", where)
        try:
            self._drain_queue(self.audio_in_queue)
        except Exception:
            pass
        try:
            self._drain_queue(self.out_queue)
        except Exception:
            pass
        logger.debug("Queues flushed (%s).", where)

    # ---------- optional simple WAV logging ----------

    async def _ensure_log_dirs(self):
        for d in (self._log_input_dir, self._log_output_dir):
            d.mkdir(parents=True, exist_ok=True)

    async def _open_turn_logs(self):
        """Open input/output WAV files for the current turn (lazy)."""
        if self._log_lock is None:
            self._log_lock = asyncio.Lock()
        async with self._log_lock:
            if self._in_wav or self._out_wav:
                return
            await self._ensure_log_dirs()
            self._turn_id += 1
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            in_path = self._log_input_dir / f"turn{self._turn_id:04d}_{ts}_in.wav"
            out_path = self._log_output_dir / f"turn{self._turn_id:04d}_{ts}_out.wav"

            # Input (16k mono, PCM16)
            self._in_wav = wave.open(str(in_path), "wb")
            self._in_wav.setnchannels(1)
            self._in_wav.setsampwidth(2)  # 16-bit
            self._in_wav.setframerate(SEND_SAMPLE_RATE)

            # Output (24k mono, PCM16)
            self._out_wav = wave.open(str(out_path), "wb")
            self._out_wav.setnchannels(1)
            self._out_wav.setsampwidth(2)
            self._out_wav.setframerate(RECEIVE_SAMPLE_RATE)

            logger.debug(
                "Turn %04d: logging to %s and %s", self._turn_id, in_path, out_path
            )

    async def _close_turn_logs(self):
        """Close any open WAVs gracefully."""
        if self._log_lock is None:
            self._log_lock = asyncio.Lock()
        async with self._log_lock:
            try:
                if self._in_wav:
                    self._in_wav.close()
            except Exception:
                logger.exception("Error closing input WAV")
            finally:
                self._in_wav = None

            try:
                if self._out_wav:
                    self._out_wav.close()
            except Exception:
                logger.exception("Error closing output WAV")
            finally:
                self._out_wav = None

    async def _log_input_bytes(self, pcm: bytes):
        """Append input PCM to the 'in' log (optional)."""
        if self._log_lock is None:
            self._log_lock = asyncio.Lock()
        async with self._log_lock:
            if self._in_wav is None:
                await self._open_turn_logs()
            try:
                self._in_wav.writeframes(pcm)
            except Exception:
                logger.exception("Failed to write input audio log")

    async def _log_output_bytes(self, pcm: bytes):
        """Append output PCM to the 'out' log (optional)."""
        if self._log_lock is None:
            self._log_lock = asyncio.Lock()
        async with self._log_lock:
            if self._out_wav is None:
                await self._open_turn_logs()
            try:
                self._out_wav.writeframes(pcm)
            except Exception:
                logger.exception("Failed to write output audio log")

    # ---------- ChatNode service helpers ----------

    def _ensure_srv_client(self):
        """
        Lazily create a ROS node + service client for CreateOrUpdateChatMessage.
        We keep this very small so AudioLoop stays decoupled from ChatNode internals.
        """
        if self._srv_node is None:
            if not rclpy.ok():
                rclpy.init()
            self._srv_node = Node("gemini_audio_loop_client")
            self._srv_client = self._srv_node.create_client(
                CreateOrUpdateChatMessage, "create_or_update_chat_message"
            )
            if not self._srv_client.wait_for_service(timeout_sec=2.0):
                logger.warning(
                    "Service 'create_or_update_chat_message' not available yet."
                )

    def _start_chat_worker(self):
        """Start background thread that handles CreateOrUpdateChatMessage calls."""
        if self._chat_worker and self._chat_worker.is_alive():
            return

        def _worker():
            logger.debug("Chat worker thread started.")
            while not self._stop_event.is_set():
                try:
                    req = self._chat_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if req is None:
                    # Sentinel for shutdown
                    break

                try:
                    self._ensure_srv_client()
                    if self._srv_client is None:
                        continue

                    future = self._srv_client.call_async(req)
                    rclpy.spin_until_future_complete(
                        self._srv_node, future, timeout_sec=1.0
                    )

                    if (
                        future.done()
                        and future.result() is not None
                        and future.result().successful
                    ):
                        # keep message_id for subsequent UPDATEs
                        self._last_pib_message_id = future.result().message_id
                except Exception:
                    logger.error(
                        "Chat worker: service call failed or timed out.", exc_info=True
                    )

            logger.debug("Chat worker thread exiting.")

        self._chat_worker = threading.Thread(target=_worker, daemon=True)
        self._chat_worker.start()

    def _start_new_stream(self, role: str):
        """
        Reset accumulation for a new logical message (role = 'user' or 'assistant').
        This ensures we create separate PIB messages for each side of the dialog.
        """
        if self._current_role is not None and self._accum_text:
            prev_is_user = self._current_role == "user"
            self._send_chat_piece(
                text_piece="",  # don’t change accumulator
                is_user=prev_is_user,
                update_db=True,
                force_flush=True,  # ignore throttle
            )

        self._current_role = role
        self._accum_text = ""
        self._last_pib_message_id = ""

    def _send_chat_piece(
        self,
        text_piece: str,
        is_user: bool,
        update_db: bool = True,
        force_flush: bool = False,
    ):
        """
        Send accumulated text to ChatNode service.

        - For user: usually throttled.
        - For assistant: typically force_flush=True -> realtime.
        """
        if self._stop_event.is_set() or not self._is_listening:
            return

        # 1) Update accumulator
        if text_piece:
            self._accum_text = (self._accum_text + " " + text_piece).strip()

        if not self._accum_text:
            return

        # 2) Build request
        req = CreateOrUpdateChatMessage.Request()
        req.chat_id = self._chat_id or ""
        req.text = self._accum_text
        req.is_user = is_user
        req.update_database = update_db
        req.message_id = self._last_pib_message_id  # "" -> CREATE on first call

        # 3) Queue for chat worker
        try:
            self._chat_queue.put_nowait(req)
        except queue.Full:
            logger.debug("Chat worker queue full, dropping chat update.")

    # ---------- tasks ----------

    async def _listen_from_ros(self):
        """Pulls PCM16 mono @16k from ROS topic into out_queue for the live session."""
        logger.debug(
            f"Listening from ROS topic '{ROS_AUDIO_TOPIC}' (expect PCM16 mono @16k)."
        )
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.debug("_listen_from_ros: cancelled")
            raise

    async def send_realtime(self):
        """Feeds PCM chunks from out_queue into the Gemini live session."""
        try:
            while not self._stop_event.is_set():
                msg = await self.out_queue.get()
                if time.monotonic() < self._mic_muted_until:
                    # pib is still speaking (or just finished) - drop this
                    # chunk instead of feeding pib's own voice back to Gemini.
                    continue
                # If desired, uncomment to log input audio:
                # data = msg.get("data", b"")
                # if data:
                #     await self._log_input_bytes(data)
                await self.session.send_realtime_input(audio=msg)
        except asyncio.CancelledError:
            logger.debug("send_realtime: cancelled")
            raise
        except Exception as e:
            if self._stop_event.is_set():
                return
            logger.warning(
                "send_realtime: upstream send failed; requesting reconnect.",
                exc_info=True,
            )
            raise ReconnectRequested("send_realtime failed") from e

    async def send_video_frames(self):
        """Feeds JPEG stills from video_out_queue into the Gemini live session.
        Only running when the active personality has camera_access_enabled."""
        try:
            while not self._stop_event.is_set():
                msg = await self.video_out_queue.get()
                await self.session.send_realtime_input(video=msg)
        except asyncio.CancelledError:
            logger.debug("send_video_frames: cancelled")
            raise
        except Exception as e:
            if self._stop_event.is_set():
                return
            logger.warning(
                "send_video_frames: upstream send failed; requesting reconnect.",
                exc_info=True,
            )
            raise ReconnectRequested("send_video_frames failed") from e

    def _log_user_transcriptions(self, sc):
        """
        Called for each server_content event from Gemini:
        - input_transcription  -> what the user said (streaming text)
        """
        if self._stop_event.is_set() or not self._is_listening:
            return

        # User stream
        input_transcription = getattr(sc, "input_transcription", None)
        if input_transcription and getattr(input_transcription, "text", None):
            text_piece = input_transcription.text.strip()
            logger.debug(f"User: {text_piece}")
            if self._current_role != "user":
                self._start_new_stream("user")
            self._send_chat_piece(
                text_piece,
                is_user=True,
                update_db=True,
                force_flush=False,
            )

    def _extract_assistant_text(self, sc) -> Optional[str]:
        """
        Extract assistant (Gemini) text from server_content without sending it.
        Return the text string or None.
        """
        output_transcription = getattr(sc, "output_transcription", None)
        if not output_transcription:
            return None

        txt = getattr(output_transcription, "text", None)
        if txt:
            text_piece = txt.strip()
            logger.debug(
                f"Gemini (buffered in _extract_assistant_text) as single object: {text_piece}"
            )
            return text_piece

        return None

    async def _handle_tool_call(self, tool_call: "genai_types.LiveServerToolCall") -> None:
        """Executes each requested move_joint/reset_pose/show_emotion call
        via RosMotorBridge/RosEmotionBridge (off the event loop, since they
        block on rclpy) and reports the outcome back to Gemini so it knows
        whether the action actually happened. Logs every call at INFO so
        what the model actually did is visible in
        `docker logs ros-voice-assistant`."""
        function_responses = []
        loop = asyncio.get_running_loop()
        for call in tool_call.function_calls:
            logger.info(f"tool call received: {call.name}({call.args!r})")
            args = call.args or {}

            if call.name == "reset_pose":
                if self._motor_bridge is None:
                    result = {"error": "movement tool not available"}
                else:
                    successful, error = await loop.run_in_executor(
                        None, self._motor_bridge.reset_pose
                    )
                    logger.info(
                        f"reset_pose -> successful={successful} error={error!r}"
                    )
                    result = (
                        {"successful": True}
                        if successful
                        else {"successful": False, "error": error}
                    )

            elif call.name == "move_joint":
                if self._motor_bridge is None:
                    result = {"error": "movement tool not available"}
                else:
                    motor_name = args.get("motor_name")
                    position = args.get("position")
                    try:
                        position = int(position)
                    except (TypeError, ValueError):
                        position = None

                    if position is None:
                        result = {"error": f"invalid position: {args.get('position')!r}"}
                    elif motor_name not in MOTOR_NAMES:
                        result = {"error": f"unknown motor_name: {motor_name!r}"}
                    else:
                        successful, error = await loop.run_in_executor(
                            None, self._motor_bridge.move_joint, motor_name, position
                        )
                        logger.info(
                            f"move_joint({motor_name!r}, {position}deg) -> "
                            f"successful={successful} error={error!r}"
                        )
                        result = (
                            {"successful": True}
                            if successful
                            else {"successful": False, "error": error}
                        )

            elif call.name == "show_emotion":
                if self._emotion_bridge is None:
                    result = {"error": "emotion tool not available"}
                else:
                    emotion = args.get("emotion")
                    image_id = EMOTION_NAME_TO_IMAGE_ID.get(emotion)
                    if image_id is None:
                        result = {"error": f"unknown emotion: {emotion!r}"}
                    else:
                        successful, error = await loop.run_in_executor(
                            None, self._emotion_bridge.show_emotion, image_id
                        )
                        logger.info(
                            f"show_emotion({emotion!r}) -> "
                            f"successful={successful} error={error!r}"
                        )
                        result = (
                            {"successful": True}
                            if successful
                            else {"successful": False, "error": error}
                        )

            else:
                result = {"error": f"unknown tool: {call.name!r}"}

            function_responses.append(
                genai_types.FunctionResponse(id=call.id, name=call.name, response=result)
            )

        try:
            await self.session.send_tool_response(function_responses=function_responses)
        except Exception:
            logger.exception("Failed to send tool response to Gemini")

    async def receive_audio(self):
        """
        Receives downstream events from Gemini:
        - resp.data -> PCM audio bytes (playback)
        - resp.text -> occasional text events
        - resp.server_content -> transcript slices:
            * user -> handled immediately in _log_user_transcriptions
            * assistant -> extracted and paired with PCM for synchronized display
        """
        while not self._stop_event.is_set():
            try:
                # New turn -> reset stream roles/accumulators so messages are separate
                self._current_role = None
                self._accum_text = ""
                self._last_pib_message_id = ""
                await self._open_turn_logs()
            except Exception as e:
                logger.error(f"Failed to open turn logs: {e}")
                continue

            turn = None
            try:
                turn = self.session.receive()
                assistant_text_piece: Optional[str] = None
                async for resp in turn:
                    # ----- Session management signals -----
                    # Session resumption checkpoints (store handle for reconnect)
                    session_resumption_update = getattr(
                        resp, "session_resumption_update", None
                    ) or getattr(resp, "sessionResumptionUpdate", None)
                    if session_resumption_update is not None:
                        new_handle = getattr(
                            session_resumption_update, "new_handle", None
                        ) or getattr(session_resumption_update, "newHandle", None)
                        resumable = getattr(
                            session_resumption_update, "resumable", None
                        )
                        if resumable and new_handle:
                            self._session_handle = new_handle

                    # GoAway warning (connection will be terminated soon)
                    go_away_signal = getattr(resp, "go_away", None) or getattr(
                        resp, "goAway", None
                    )
                    if go_away_signal is not None:
                        time_left = getattr(
                            go_away_signal, "time_left", None
                        ) or getattr(go_away_signal, "timeLeft", None)
                        logger.warning(
                            "GoAway received (time_left=%s). Reconnecting...", time_left
                        )
                        raise ReconnectRequested("go_away")

                    # move_joint tool calls (only present when the active
                    # personality has movement_access_enabled - see run()).
                    tool_call = getattr(resp, "tool_call", None)
                    if tool_call is not None and tool_call.function_calls:
                        await self._handle_tool_call(tool_call)

                    # Handle transcripts (user now, assistant buffered)
                    sc = getattr(resp, "server_content", None)
                    if sc is not None:
                        # User text is sent immediately
                        self._log_user_transcriptions(sc)
                        # Assistant text is only extracted and passed along
                        new_piece = self._extract_assistant_text(sc)
                        if new_piece:
                            assistant_text_piece = new_piece
                            logger.debug(
                                f"Buffered for upcoming audio: {assistant_text_piece}"
                            )

                    if data := getattr(resp, "data", None):
                        # PCM audio from Gemini (24k mono)
                        try:
                            # Put a pair: (pcm_bytes, assistant_text_piece or None)
                            queued_text = assistant_text_piece
                            logger.debug(f"Queueing audio with text: {queued_text}")

                            self.audio_in_queue.put_nowait((data, assistant_text_piece))
                            if assistant_text_piece is not None:
                                assistant_text_piece = None
                            # If desired, uncomment to log output audio:
                            # await self._log_output_bytes(data)
                        except asyncio.QueueFull:
                            logger.warning(
                                "Audio input queue is full; dropping data chunk."
                            )
                    elif text := getattr(resp, "text", None):
                        # Occasionally text responses arrive without audio; print for debugging
                        print(text, end="")

                    if self._stop_event.is_set():
                        # Stop requested -> break out and let run() tear down
                        break

            except ReconnectRequested:
                raise

            except Exception as e:
                if self._stop_event.is_set():
                    return
                logger.warning(
                    "receive_audio: downstream receive failed; requesting reconnect.",
                    exc_info=True,
                )
                raise ReconnectRequested("receive_audio failed") from e

            # Clear any leftover audio between turns
            while not self.audio_in_queue.empty():
                self.audio_in_queue.get_nowait()

    async def play_audio(self):
        """PyAudio playback consumer for PCM @24k mono + synchronized Gemini text."""
        self.playback_stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        try:
            logger.info(
                "Playback stream opened: rate=%s, channels=%s",
                RECEIVE_SAMPLE_RATE,
                CHANNELS,
            )
        except Exception:
            pass

        try:
            while not self._stop_event.is_set():
                item = await self.audio_in_queue.get()
                # Expecting a pair: (pcm_bytes, assistant_text_piece or None)
                pcm, assistant_text_piece = item

                # Extend the mic-mute window before playing so the mic is
                # already ignored once this chunk's sound reaches it, and
                # keeps being ignored as long as more chunks keep arriving.
                self._mic_muted_until = time.monotonic() + MIC_MUTE_TRAIL_S

                # Play the audio
                await asyncio.to_thread(self.playback_stream.write, pcm)
                # If there is Gemini text attached to this PCM chunk, send it now.
                logger.debug(f"writing {assistant_text_piece} as gemini in UI")

                if assistant_text_piece:
                    # Ensure we are in assistant stream
                    if self._current_role != "assistant":
                        self._start_new_stream("assistant")
                    logger.debug(f"sending {assistant_text_piece} to the worker")

                    self._send_chat_piece(
                        assistant_text_piece,
                        is_user=False,
                        update_db=True,
                        force_flush=True,
                    )

        except asyncio.CancelledError:
            logger.debug("play_audio: cancelled, closing playback stream")
            try:
                self.playback_stream.close()
            finally:
                raise
        except Exception:
            logger.exception("play_audio error")

    async def run(self):
        """
        Main async entry:
        - Maintains a Gemini live session, reconnecting automatically on GoAway / disconnect.
        - Enables context window compression + session resumption (optional via env vars).
        - Starts ROS bridge + tasks (send/receive/play).
        """
        client = genai.Client(api_key=self.api_key)

        # Read chat personality/description from PIB to seed the model (once)
        description = "You are pib, a humanoid robot."
        camera_enabled = False
        movement_enabled = False
        emotion_enabled = False
        try:
            successful, personality = voice_assistant_client.get_personality_from_chat(
                self._chat_id
            )
            if not successful:
                logger.error(f"no personality found for id {self._chat_id}")
            else:
                if getattr(personality, "description", None):
                    description = personality.description
                camera_enabled = bool(
                    getattr(personality, "camera_access_enabled", False)
                )
                movement_enabled = bool(
                    getattr(personality, "movement_access_enabled", False)
                )
                emotion_enabled = bool(
                    getattr(personality, "emotion_access_enabled", False)
                )
        except Exception:
            logger.exception(
                "Failed to fetch personality; using default system instruction."
            )

        if camera_enabled:
            # Without this, Gemini has no way of knowing the incoming video
            # blobs are its own camera feed and defaults to denying it has
            # any camera access at all.
            description = (
                description
                + "\n\nDu hast eine Kamera und bekommst laufend aktuelle Bilder "
                "von dem, was gerade vor dir zu sehen ist. Wenn jemand dich "
                "fragt, was du siehst oder was gerade passiert, beschreibe "
                "das zuletzt empfangene Kamerabild. Behaupte niemals, dass "
                "du keinen Kamerazugriff hast."
            )

        if movement_enabled:
            # Without this, Gemini has no way of knowing it can actually
            # move the robot and defaults to claiming it cannot. The full
            # motor_name -> German description list is included as plain
            # readable text (not just buried in the move_joint tool
            # schema's enum) so the model can actually name joints
            # correctly and reliably pick the right one, e.g. for "heb den
            # Arm" -> shoulder_vertical_left/right.
            description = (
                description
                + "\n\nDu kannst deinen eigenen Koerper tatsaechlich bewegen "
                "- das ist keine Simulation, ruf dazu WIRKLICH die Funktion "
                "move_joint auf (nicht nur ankuendigen, dass du es tust). "
                "Verfuegbare Gelenke (motor_name: Bedeutung):\n"
                + MOTOR_NAME_DESCRIPTIONS
                + "\n\nposition ist der Zielwinkel in GRAD (nicht Prozent!), "
                "typischerweise -90 bis 90, 0 ist meist die Mittelstellung. "
                "Nutze spuerbare Winkeldifferenzen (z.B. 30-60 Grad) - sehr "
                "kleine Werte (wenige Grad) sind auf pib kaum sichtbar. Fuer "
                "'heb den Arm' reicht meist EIN Aufruf von "
                "shoulder_vertical_left oder shoulder_vertical_right mit "
                "einem deutlichen Winkel. Sobald eine gezeigte Bewegung/"
                "Geste abgeschlossen ist, rufe reset_pose auf, um wieder in "
                "die neutrale Ausgangshaltung zurueckzukehren - bleib nicht "
                "in einer verdrehten Position stehen. Bewege Gelenke nur, "
                "wenn explizit danach gefragt wird oder es zur Situation "
                "passt. Behaupte niemals, dass du dich nicht bewegen "
                "kannst oder die Gelenknamen nicht kennst - sie stehen "
                "oben."
            )

        if emotion_enabled:
            # Without this, Gemini has no way of knowing it can actually
            # change its own facial expression.
            description = (
                description
                + "\n\nDu kannst deine Augen auf dem Display veraendern, um "
                "Gefuehle auszudruecken: ruf dazu show_emotion mit einem "
                "passenden Gesichtsausdruck auf (z.B. 'happy', 'surprised', "
                "'sad'), wann immer es zur Stimmung des Gespraechs passt - "
                "nicht nur auf Nachfrage, sondern von dir aus waehrend des "
                "Sprechens. Rufe 'neutral' auf, um wieder ruhig dreinzuschauen."
            )

        base_config = dict(CONFIG)
        base_config["system_instruction"] = description
        tools = []
        if movement_enabled:
            tools.extend(MOVE_JOINT_TOOL["function_declarations"])
        if emotion_enabled:
            tools.extend(SHOW_EMOTION_TOOL["function_declarations"])
        if tools:
            base_config["tools"] = [{"function_declarations": tools}]

        async def _connect_config():
            connection_config = dict(base_config)

            if ENABLE_CONTEXT_COMPRESSION:
                connection_config["context_window_compression"] = {
                    "trigger_tokens": CWC_TRIGGER_TOKENS,
                    "sliding_window": {"target_tokens": CWC_TARGET_TOKENS},
                }

            if ENABLE_SESSION_RESUMPTION:
                # Gemini Developer API supports sessi:contentReference[oaicite:3]{index=3}dle,
                # but NOT the 'transparent' parameter.
                sr = {"handle": self._session_handle if self._session_handle else None}
                connection_config["session_resumption"] = sr

            return connection_config

        # Outer loop: reconnect as needed until stopped
        while not self._stop_event.is_set():
            ros_started = False
            tasks = []
            try:
                gemini_config = await _connect_config()

                async with client.aio.live.connect(
                    model=MODEL, config=gemini_config
                ) as session:
                    self.session = session
                    self.audio_in_queue = asyncio.Queue[tuple[bytes, Optional[str]]]()
                    self.out_queue = asyncio.Queue(maxsize=5)
                    self.video_out_queue = asyncio.Queue(maxsize=2)
                    self._log_lock = asyncio.Lock()

                    # Optional folders for WAV logs
                    await self._ensure_log_dirs()

                    # Start ROS subscriber thread that feeds PCM into out_queue
                    topic = os.getenv("ROS_AUDIO_TOPIC", "audio_stream")
                    self._ros_bridge = RosAudioBridge(
                        topic, asyncio.get_running_loop(), self.out_queue
                    )
                    self._ros_bridge.start()
                    ros_started = True
                    logger.info("RosAudioBridge started.")

                    # Start async tasks
                    tasks = [
                        asyncio.create_task(self._listen_from_ros()),
                        asyncio.create_task(self.send_realtime()),
                        asyncio.create_task(self.receive_audio()),
                        asyncio.create_task(self.play_audio()),
                    ]

                    # Camera is opt-in per personality: only poll/send video
                    # when camera_access_enabled is set on the active personality.
                    if camera_enabled:
                        self._camera_bridge = RosCameraBridge(
                            asyncio.get_running_loop(),
                            self.video_out_queue,
                            GEMINI_VIDEO_INTERVAL_S,
                        )
                        self._camera_bridge.start()
                        logger.info(
                            "RosCameraBridge started (camera_access_enabled=True)."
                        )
                        tasks.append(asyncio.create_task(self.send_video_frames()))

                    # Movement is opt-in per personality: the move_joint tool
                    # call is only usable (and only advertised to Gemini via
                    # base_config["tools"] above) when movement_access_enabled
                    # is set on the active personality.
                    if movement_enabled:
                        self._motor_bridge = RosMotorBridge()
                        logger.info(
                            "RosMotorBridge ready (movement_access_enabled=True)."
                        )

                    # Emotions are opt-in per personality, independent of
                    # movement_access_enabled: the show_emotion tool call is
                    # only usable (and only advertised to Gemini via
                    # base_config["tools"] above) when emotion_access_enabled
                    # is set on the active personality.
                    if emotion_enabled:
                        self._emotion_bridge = RosEmotionBridge()
                        logger.info(
                            "RosEmotionBridge ready (emotion_access_enabled=True)."
                        )

                    # Wait until one task errors (or requests reconnect)
                    done, pending = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_EXCEPTION
                    )
                    for t in done:
                        exc = t.exception()
                        if exc:
                            raise exc

                    # No exception, session ended normally -> stop loop
                    logger.info("Live session ended normally; stopping.")
                    break

            except ReconnectRequested as e:
                if self._stop_event.is_set():
                    break
                logger.info(
                    "Reconnect requested (%s). session_handle=%s",
                    str(e),
                    "present" if self._session_handle else "none",
                )

            except asyncio.CancelledError:
                logger.debug("GeminiAudioLoop.run: cancelled")
                break

            except Exception:
                logger.exception("GeminiAudioLoop.run: unexpected error")
                break

            finally:
                # Cancel all tasks and wait; ignore exceptions during teardown
                for t in tasks:
                    try:
                        t.cancel()
                    except Exception:
                        pass
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                # Stop ROS bridge if it was started
                if ros_started and self._ros_bridge:
                    try:
                        self._ros_bridge.stop()
                    except Exception:
                        pass
                    self._ros_bridge = None

                # Stop camera bridge if it was started
                if self._camera_bridge:
                    try:
                        self._camera_bridge.stop()
                    except Exception:
                        pass
                    self._camera_bridge = None

                # Close playback stream if still open
                if self.playback_stream:
                    try:
                        self.playback_stream.close()
                    except Exception:
                        pass
                    self.playback_stream = None

                # Drain queues and close WAVs
                try:
                    await self._flush_queues("shutdown")
                except Exception:
                    pass
                try:
                    await self._close_turn_logs()
                except Exception:
                    pass

                self.session = None

            # Backoff before reconnecting
            if not self._stop_event.is_set():
                await asyncio.sleep(LIVE_RECONNECT_BACKOFF_S)

        logger.info("GeminiAudioLoop.run: terminated")


def main():
    # Optional local entry for quick manual test (not used in ROS launch)
    loop = GeminiAudioLoop(api_key=os.getenv("GOOGLE_API_KEY", ""))
    loop.start()


if __name__ == "__main__":
    main()
