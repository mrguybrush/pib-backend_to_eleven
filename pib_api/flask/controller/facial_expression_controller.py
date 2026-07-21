from flask import Blueprint, jsonify, request, send_file

from service import facial_expression_service
from schema.facial_expression_schema import (
    facial_expressions_schema,
    facial_expression_schema,
)

bp = Blueprint("facial_expression_controller", __name__)

# Animated (gif) or static (png/jpeg) images are all accepted - the display
# node picks the right rendering path (animation vs. single still image)
# based on this same magic-byte sniff, see facial_expression_service.
_GIF_MAGIC = (b"GIF87a", b"GIF89a")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def _detect_mimetype(data: bytes) -> str | None:
    if data.startswith(_GIF_MAGIC):
        return "image/gif"
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    return None


def _read_and_validate_image() -> bytes | tuple:
    """Reads the uploaded 'file' field and checks it's a gif/png/jpeg via
    its magic header. Returns the raw bytes, or a (response, status) tuple
    to return as-is on error."""
    if "file" not in request.files:
        return jsonify({"error": "no file provided (field name 'file')"}), 400
    image_bytes = request.files["file"].read()
    if _detect_mimetype(image_bytes) is None:
        return jsonify({"error": "not a valid gif/png/jpeg file"}), 400
    return image_bytes


@bp.route("", methods=["GET"])
def get_all_facial_expressions():
    expressions = facial_expression_service.get_all_facial_expressions()
    return jsonify(
        {"facialExpressions": facial_expressions_schema.dump(expressions)}
    )


@bp.route("", methods=["POST"])
def create_facial_expression():
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    gif_bytes = _read_and_validate_image()
    if isinstance(gif_bytes, tuple):
        return gif_bytes
    try:
        expression = facial_expression_service.create_facial_expression(
            name, gif_bytes
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return facial_expression_schema.dump(expression), 201


@bp.route("/order", methods=["PUT"])
def reorder_facial_expressions():
    """Persistiert die Drag&Drop-Reihenfolge.
    Body: {"expressionIds": ["<uuid>", ...]} in gewuenschter Anzeige-Reihenfolge."""
    expression_ids = (request.json or {}).get("expressionIds", [])
    facial_expression_service.reorder_facial_expressions(expression_ids)
    return "", 204


@bp.route("/<string:expression_id>", methods=["PATCH"])
def rename_facial_expression(expression_id: str):
    name = ((request.json or {}).get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        expression = facial_expression_service.rename_facial_expression(
            expression_id, name
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return facial_expression_schema.dump(expression)


@bp.route("/<string:expression_id>/gif", methods=["PUT"])
def replace_facial_expression_gif(expression_id: str):
    gif_bytes = _read_and_validate_image()
    if isinstance(gif_bytes, tuple):
        return gif_bytes
    try:
        facial_expression_service.replace_gif(expression_id, gif_bytes)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return "", 204


@bp.route("/<string:expression_id>/gif", methods=["GET"])
def get_facial_expression_gif(expression_id: str):
    try:
        path = facial_expression_service.get_gif_path(expression_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    with open(path, "rb") as f:
        header = f.read(16)
    mimetype = _detect_mimetype(header) or "application/octet-stream"
    return send_file(path, mimetype=mimetype)


@bp.route("/<string:expression_id>", methods=["DELETE"])
def delete_facial_expression(expression_id: str):
    try:
        facial_expression_service.delete_facial_expression(expression_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return "", 204
