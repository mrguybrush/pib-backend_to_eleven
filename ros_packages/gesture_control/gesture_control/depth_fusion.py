"""
Fusion der Browser-2D-Landmarks mit dem echten Stereo-Tiefenbild der OAK-D.

Der Browser (MediaPipe) liefert praezise x/y-Positionen, aber nur eine vom
Modell GESCHAETZTE Tiefe (z) - daran scheiterten bisher vor allem Ober-/
Unterarm-Rotation und teils der Ellbogen. Der Kamera-Node publiziert auf
"depth_map" ein kleines, auf die RGB-Sicht ausgerichtetes Tiefenbild
(uint16 Millimeter, base64, siehe camera/oak_d_lite/stereo.py). Diese Klasse
ersetzt damit die Modell-z durch Messwerte und rechnet alle Punkte in ein
konsistentes metrisches Koordinatensystem um - Winkel zwischen Vektoren
werden dadurch geometrisch korrekt.

Konsistenzregel: solange ein frisches Tiefenbild vorliegt, wird IMMER
fusioniert (Punkte ohne gueltige Tiefe werden weggelassen, statt sie mit
anderer Einheiten-Skala zu mischen - fehlende Punkte lassen den jeweiligen
Kandidaten sauber auf None fallen und das Gelenk haelt seine Position).
Ohne Tiefenbild (Feature aus/Quelle Webcam) geht die Payload unveraendert
durch, alles verhaelt sich wie bisher.
"""
import base64
import json
import math
import time
from array import array
from typing import Optional

# Muss zur Payload des Kamera-Nodes passen (DEPTH_MAP_W/H in stereo.py).
# Seitenverhaeltnis 16:9 entspricht dem RGB-Preview (1280x720) - die
# aspect-skalierten x-Koordinaten der Browser-Payload (x in [0..16/9])
# lassen sich damit direkt aufs Tiefenbild abbilden.
ASPECT = 16.0 / 9.0

# Blickfeld der OAK-D-Lite-RGB-Kamera im 16:9-Videomodus (~69 Grad
# horizontal, Herstellerangabe IMX214). Vertikal folgt aus quadratischen
# Pixeln: tan(vfov/2) = tan(hfov/2) * 9/16.
_KX = math.tan(math.radians(69.0 / 2.0))
_KY = _KX * (1.0 / ASPECT)

# Tiefenbild aelter als das hier -> nicht mehr fusionieren (Passthrough)
MAP_MAX_AGE_S = 0.7
# Fenster-Halbbreiten fuers Sampling im Tiefenbild: erst klein (5x5), bei
# Stereo-Loechern (typisch an Objektkanten, z.B. Handgelenk vor dem
# Hintergrund) groesser ausweichen (11x11).
_SAMPLE_HALF_WINDOWS = (2, 5)
# Stereo liefert 0 fuer "keine Messung"; alles darueber hinaus ist fuer
# Personen vor pib unplausibel (Rauschen/Hintergrund weit weg).
_MAX_PLAUSIBLE_MM = 6000


class DepthFusion:
    def __init__(self):
        self._depth: Optional[array] = None  # uint16 mm, row-major
        self._w = 0
        self._h = 0
        self._time = 0.0

    def update(self, json_payload: str) -> None:
        """Neues Tiefenbild vom Kamera-Node (depth_map-Topic)."""
        try:
            parsed = json.loads(json_payload)
            raw = base64.b64decode(parsed["data"])
            depth = array("H")  # little-endian auf dem Pi (arm64)
            depth.frombytes(raw)
            if len(depth) != int(parsed["w"]) * int(parsed["h"]):
                return
        except (KeyError, ValueError, TypeError):
            return
        self._depth = depth
        self._w = int(parsed["w"])
        self._h = int(parsed["h"])
        self._time = time.monotonic()

    def has_fresh_map(self) -> bool:
        return (
            self._depth is not None
            and time.monotonic() - self._time < MAP_MAX_AGE_S
        )

    def fuse(self, payload: dict) -> dict:
        """Ersetzt Modell-z durch gemessene Tiefe (siehe Modul-Kommentar).
        Ohne frisches Tiefenbild: Payload unveraendert zurueck."""
        if not self.has_fresh_map():
            return payload

        pose_out = {}
        for name, values in payload.get("pose", {}).items():
            point = self._to_metric(values[0], values[1])
            if point is None:
                continue
            x, y, z = point
            score = values[2] if len(values) > 2 else 1.0
            pose_out[name] = [x, y, score, z]

        hands_out = {}
        for side, points in payload.get("hands", {}).items():
            hand = {}
            for name, values in points.items():
                point = self._to_metric(values[0], values[1])
                if point is None:
                    continue
                x, y, z = point
                # 4 Elemente, damit retargeting._as_xyz das echte z (Index
                # 3) uebernimmt - bei den 3er-Listen des Browsers ging die
                # Hand-z bisher verloren.
                hand[name] = [x, y, 0.0, z]
            if hand:
                hands_out[side] = hand

        return {"pose": pose_out, "hands": hands_out}

    def _to_metric(self, x_scaled: float, y_norm: float):
        """Aspect-skaliertes (x, y) der Payload -> metrischer 3D-Punkt
        (Meter) via gemessener Tiefe, oder None ohne gueltige Messung."""
        x_norm = x_scaled / ASPECT
        depth_mm = self._sample_depth(x_norm, y_norm)
        if depth_mm is None:
            return None
        d = depth_mm / 1000.0
        x = (x_norm - 0.5) * 2.0 * _KX * d
        y = (y_norm - 0.5) * 2.0 * _KY * d
        return (x, y, d)

    def _sample_depth(self, x_norm: float, y_norm: float) -> Optional[float]:
        """Tiefenwert am Punkt: NAECHSTLIEGENDES Quartil der gueltigen Werte
        in einem kleinen Fenster (bei Loechern groesseres Ausweichfenster).

        Bewusst kein Median: bei angewinkeltem Ellbogen zeigt der Unterarm
        zur Kamera, das Handgelenk ist im Bild klein und steht vor dem
        Hintergrund - ein Median kippt dann auf den Hintergrund (oder es
        gibt an der Objektkante gar keine Messung) und der Ellbogenwinkel
        friert ein. Die Person steht immer VOR dem Hintergrund, also ist
        das nahe Quartil der robuste Schaetzer fuer "Koerperoberflaeche am
        Landmark" und bleibt trotzdem unempfindlich gegen einzelne
        Rausch-Pixel."""
        if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
            return None
        u = int(round(x_norm * (self._w - 1)))
        v = int(round(y_norm * (self._h - 1)))
        for half_window in _SAMPLE_HALF_WINDOWS:
            values = []
            for dv in range(-half_window, half_window + 1):
                row = v + dv
                if row < 0 or row >= self._h:
                    continue
                base = row * self._w
                for du in range(-half_window, half_window + 1):
                    col = u + du
                    if col < 0 or col >= self._w:
                        continue
                    value = self._depth[base + col]
                    if 0 < value <= _MAX_PLAUSIBLE_MM:
                        values.append(value)
            if values:
                values.sort()
                return float(values[len(values) // 4])
        return None
