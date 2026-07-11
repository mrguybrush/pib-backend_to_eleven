import os
import wave
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

bp = Blueprint("voice_recording_controller", __name__)

# Same directory mounted into ros-voice-assistant (see docker-compose.yaml) -
# the play_wav Blockly block only ever sends this path (plus a filename) to
# the play_audio_from_file ROS service, so both containers must agree on it.
VOICE_RECORDINGS_DIR = os.getenv(
    "VOICE_RECORDINGS_DIR", "/home/pib/voice_recordings"
)


def _safe_path(filename: str) -> str | None:
    """Resolves filename within VOICE_RECORDINGS_DIR, refusing anything that
    would escape it (path traversal) or isn't a plain filename."""
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return None
    path = os.path.join(VOICE_RECORDINGS_DIR, safe_name)
    if os.path.dirname(path) != VOICE_RECORDINGS_DIR.rstrip("/"):
        return None
    return path


@bp.route("", methods=["GET"])
def get_voice_recordings():
    os.makedirs(VOICE_RECORDINGS_DIR, exist_ok=True)
    recordings = []
    for filename in sorted(os.listdir(VOICE_RECORDINGS_DIR)):
        if not filename.lower().endswith(".wav"):
            continue
        path = os.path.join(VOICE_RECORDINGS_DIR, filename)
        stat = os.stat(path)
        recordings.append(
            {
                "filename": filename,
                "sizeBytes": stat.st_size,
                "createdAt": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return jsonify({"recordings": recordings})


@bp.route("", methods=["POST"])
def upload_voice_recording():
    os.makedirs(VOICE_RECORDINGS_DIR, exist_ok=True)

    if "file" not in request.files:
        return jsonify({"error": "no file provided (field name 'file')"}), 400
    file = request.files["file"]

    filename = secure_filename(file.filename or "")
    if not filename.lower().endswith(".wav"):
        return jsonify({"error": "only .wav files are accepted"}), 400

    # avoid overwriting an existing recording silently
    path = os.path.join(VOICE_RECORDINGS_DIR, filename)
    if os.path.exists(path):
        stem, ext = os.path.splitext(filename)
        for i in range(2, 1000):
            candidate = f"{stem} ({i}){ext}"
            candidate_path = os.path.join(VOICE_RECORDINGS_DIR, candidate)
            if not os.path.exists(candidate_path):
                filename, path = candidate, candidate_path
                break

    file.save(path)

    # reject anything that isn't actually a playable WAV file (the ROS
    # service that plays these back uses python's 'wave' module, which can
    # only read canonical PCM WAV) - better to fail the upload than to save
    # a file that later silently fails to play.
    try:
        with wave.open(path, "rb"):
            pass
    except Exception as e:
        os.remove(path)
        return jsonify({"error": f"not a valid WAV file: {e}"}), 400

    return jsonify({"filename": filename}), 201


@bp.route("/<path:filename>", methods=["DELETE"])
def delete_voice_recording(filename: str):
    path = _safe_path(filename)
    if path is None or not os.path.isfile(path):
        return jsonify({"error": "recording not found"}), 404
    os.remove(path)
    return "", 204


@bp.route("/<path:filename>", methods=["GET"])
def get_voice_recording_file(filename: str):
    """Serves the raw WAV bytes, for browser playback (<audio src=...>)."""
    path = _safe_path(filename)
    if path is None or not os.path.isfile(path):
        return jsonify({"error": "recording not found"}), 404
    return send_from_directory(VOICE_RECORDINGS_DIR, filename, mimetype="audio/wav")
