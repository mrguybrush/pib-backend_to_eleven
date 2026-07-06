"""
Lokale Text-to-Speech-Synthese ueber Piper (offline, ohne Cloud).

Liefert rohe PCM-Audiodaten (16-bit, mono, 16000 Hz) als Iterable[bytes] --
exakt das gleiche Ausgabeformat wie public_voice_client.text_to_speech(),
damit der AudioPlayerNode die Daten unveraendert weiterverarbeiten kann.

Es werden drei Synthese-Wege unterstuetzt (in dieser Reihenfolge versucht):
  1. Neue Python-API  (paket "piper", OHF-Voice/piper1-gpl):
     voice.synthesize(text) -> AudioChunk mit .audio_int16_bytes
  2. Alte Python-API  (paket "piper-tts", rhasspy):
     voice.synthesize_stream_raw(text) -> yield int16-bytes
  3. Binary-Subprocess (~/piper/piper/piper --output-raw)

Damit funktioniert derselbe Code sowohl im ROS-Container (Python-Paket)
als auch nativ auf dem Host (heruntergeladenes Binary).

Piper gibt Audio in der nativen Samplerate der Stimme aus (16000 Hz fuer
-low-Modelle, 22050 Hz fuer -medium/-high). Da der AudioPlayer fest mit
16000 Hz abspielt, wird bei abweichender Rate auf 16000 Hz resampled.

Verzeichnis der Stimmen (per Env PIPER_HOME ueberschreibbar, sonst ~/piper):
    <PIPER_HOME>/voices/<name>/<name>.onnx
    <PIPER_HOME>/voices/<name>/<name>.onnx.json
    <PIPER_HOME>/piper/piper                      (nur fuer Binary-Weg)
"""

import audioop
import json
import os
import subprocess
from typing import Iterable, Optional

# Zielformat des AudioPlayers (SPEECH_ENCODING): 16-bit mono @ 16 kHz
TARGET_SAMPLE_RATE = 16000
TARGET_SAMPLE_WIDTH = 2  # bytes pro Sample (16-bit)

PIPER_HOME = os.environ.get("PIPER_HOME", os.path.expanduser("~/piper"))
PIPER_BINARY = os.path.join(PIPER_HOME, "piper", "piper")
VOICES_DIR = os.path.join(PIPER_HOME, "voices")

# Cache geladener PiperVoice-Objekte (Modell-Laden ist teuer).
_voice_cache: dict = {}


def _voice_paths(voice_model: str) -> tuple[str, str]:
    """Liefert (onnx-Pfad, config-Pfad) fuer einen Stimmen-Namen."""
    onnx = os.path.join(VOICES_DIR, voice_model, f"{voice_model}.onnx")
    config = f"{onnx}.json"
    return onnx, config


def _get_voice_sample_rate(config_path: str) -> int:
    """Liest die native Samplerate der Stimme aus der .onnx.json-Config."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return int(config.get("audio", {}).get("sample_rate", TARGET_SAMPLE_RATE))
    except Exception:
        return TARGET_SAMPLE_RATE


def is_available(voice_model: str) -> bool:
    """Prueft, ob die Stimmen-Dateien vorhanden sind (Modell + Config)."""
    onnx, config = _voice_paths(voice_model)
    return os.path.isfile(onnx) and os.path.isfile(config)


def _resample_if_needed(
    pcm: bytes, native_rate: int, rate_state
) -> tuple[bytes, object]:
    """Resampelt einen PCM-Block auf 16 kHz, falls die native Rate abweicht."""
    if native_rate == TARGET_SAMPLE_RATE:
        return pcm, rate_state
    pcm, rate_state = audioop.ratecv(
        pcm, TARGET_SAMPLE_WIDTH, 1, native_rate, TARGET_SAMPLE_RATE, rate_state
    )
    return pcm, rate_state


def _load_python_voice(onnx: str, config: str):
    """
    Laedt eine PiperVoice ueber die Python-API (falls das Paket installiert
    ist). Liefert (voice, api_variant) oder None, wenn kein Python-Paket da ist.
    api_variant: "new" (synthesize) oder "old" (synthesize_stream_raw).
    """
    cache_key = onnx
    if cache_key in _voice_cache:
        return _voice_cache[cache_key]

    try:
        from piper import PiperVoice  # type: ignore
    except Exception:
        try:
            from piper.voice import PiperVoice  # type: ignore
        except Exception:
            return None

    try:
        try:
            voice = PiperVoice.load(onnx, config_path=config)
        except TypeError:
            # aeltere Signatur ohne config_path-Keyword
            voice = PiperVoice.load(onnx, config)
    except Exception:
        return None

    # API-Variante bestimmen
    if hasattr(voice, "synthesize"):
        variant = "new"
    elif hasattr(voice, "synthesize_stream_raw"):
        variant = "old"
    else:
        return None

    _voice_cache[cache_key] = (voice, variant)
    return _voice_cache[cache_key]


def _synthesize_python(voice, variant: str, text: str, native_rate: int):
    """Synthese ueber die Python-API. Yieldet 16-kHz-PCM-Bloecke."""
    rate_state = None

    if variant == "new":
        # Neue API: iterator von AudioChunk-Objekten.
        for chunk in voice.synthesize(text):
            pcm = getattr(chunk, "audio_int16_bytes", None)
            if pcm is None:
                continue
            # Manche Versionen liefern die Rate pro Chunk mit.
            chunk_rate = getattr(chunk, "sample_rate", native_rate)
            pcm, rate_state = _resample_if_needed(pcm, chunk_rate, rate_state)
            yield pcm
    else:
        # Alte API: iterator von rohen int16-bytes.
        for pcm in voice.synthesize_stream_raw(text):
            pcm, rate_state = _resample_if_needed(pcm, native_rate, rate_state)
            yield pcm


def _synthesize_binary(text: str, onnx: str, config: str, native_rate: int):
    """Synthese ueber das Piper-Binary (Subprocess). Yieldet 16-kHz-PCM."""
    if not os.path.isfile(PIPER_BINARY):
        raise RuntimeError(f"Piper-Binary nicht gefunden: {PIPER_BINARY}")

    cmd = [
        PIPER_BINARY,
        "--model", onnx,
        "--config", config,
        "--output-raw",
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(text.encode("utf-8"))
    proc.stdin.close()

    rate_state = None
    while True:
        pcm = proc.stdout.read(4096)
        if not pcm:
            break
        pcm, rate_state = _resample_if_needed(pcm, native_rate, rate_state)
        yield pcm

    proc.wait()
    if proc.returncode not in (0, None):
        raise RuntimeError(f"Piper endete mit Fehlercode {proc.returncode}")


def text_to_speech(text: str, voice_model: str) -> Iterable[bytes]:
    """
    Wandelt Text lokal in Sprache um und liefert rohe PCM-Bytes
    (16-bit, mono, 16000 Hz) als Iterable[bytes].

    :param text: Der zu sprechende Text.
    :param voice_model: Datei-Praefix der Stimme, z.B. "de_DE-thorsten-low".
    :raises RuntimeError: wenn kein Synthese-Weg verfuegbar ist.
    """
    onnx, config = _voice_paths(voice_model)
    if not os.path.isfile(onnx):
        raise RuntimeError(f"Piper-Stimmmodell nicht gefunden: {onnx}")

    # Ein Zeilenumbruch am Ende kann bei Piper Text abschneiden -> bereinigen.
    clean_text = text.replace("\n", " ").strip()
    if not clean_text:
        return

    native_rate = _get_voice_sample_rate(config)

    # 1./2. Python-API bevorzugen (im Container installiert).
    loaded = _load_python_voice(onnx, config)
    if loaded is not None:
        voice, variant = loaded
        yield from _synthesize_python(voice, variant, clean_text, native_rate)
        return

    # 3. Fallback: Binary-Subprocess (nativ auf dem Host).
    yield from _synthesize_binary(clean_text, onnx, config, native_rate)
