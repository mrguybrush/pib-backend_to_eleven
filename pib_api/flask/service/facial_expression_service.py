import os
from typing import List

from app.app import db
from model.facial_expression_model import FacialExpression

# Gemountetes Verzeichnis (siehe docker-compose.yaml) - eine GIF-Datei pro
# Gesichtsausdruck, benannt nach der internen expression_id (nicht dem vom
# Nutzer vergebenen Namen), damit Umbenennen keine Datei-Operationen braucht.
FACIAL_EXPRESSIONS_DIR = os.getenv(
    "FACIAL_EXPRESSIONS_DIR", "/home/pib/custom_facial_expressions"
)


def _gif_path(expression_id: str) -> str:
    return os.path.join(FACIAL_EXPRESSIONS_DIR, f"{expression_id}.gif")


def get_all_facial_expressions() -> List[FacialExpression]:
    """Sortiert nach der Drag&Drop-Reihenfolge (NULL = nie einsortiert,
    faellt ans Ende, danach alphabetisch)."""
    return FacialExpression.query.order_by(
        db.func.coalesce(FacialExpression.sort_index, 1_000_000).asc(),
        FacialExpression.name.asc(),
    ).all()


def get_facial_expression(expression_id: str) -> FacialExpression:
    expression = FacialExpression.query.filter_by(
        expression_id=expression_id
    ).first()
    if expression is None:
        raise ValueError(f"Facial expression '{expression_id}' not found")
    return expression


def create_facial_expression(name: str, gif_bytes: bytes) -> FacialExpression:
    if FacialExpression.query.filter_by(name=name).first() is not None:
        raise ValueError(f"Facial expression '{name}' already exists")
    expression = FacialExpression(name=name)
    db.session.add(expression)
    db.session.flush()  # populates expression.expression_id (default=generate_uuid)

    os.makedirs(FACIAL_EXPRESSIONS_DIR, exist_ok=True)
    with open(_gif_path(expression.expression_id), "wb") as f:
        f.write(gif_bytes)

    return expression


def rename_facial_expression(expression_id: str, name: str) -> FacialExpression:
    expression = get_facial_expression(expression_id)
    if (
        FacialExpression.query.filter_by(name=name).first() is not None
        and expression.name != name
    ):
        raise ValueError(f"Facial expression '{name}' already exists")
    expression.name = name
    db.session.flush()
    return expression


def replace_gif(expression_id: str, gif_bytes: bytes) -> None:
    expression = get_facial_expression(expression_id)
    os.makedirs(FACIAL_EXPRESSIONS_DIR, exist_ok=True)
    with open(_gif_path(expression.expression_id), "wb") as f:
        f.write(gif_bytes)


def delete_facial_expression(expression_id: str) -> None:
    expression = get_facial_expression(expression_id)
    path = _gif_path(expression.expression_id)
    db.session.delete(expression)
    db.session.flush()
    if os.path.exists(path):
        os.remove(path)


def get_gif_path(expression_id: str) -> str:
    expression = get_facial_expression(expression_id)
    path = _gif_path(expression.expression_id)
    if not os.path.isfile(path):
        raise ValueError(f"No gif stored for '{expression_id}'")
    return path


def reorder_facial_expressions(expression_ids: List[str]) -> None:
    """Persists the drag&drop order: sort_index = position in the given
    list. Ids not in the list keep their old index."""
    index_by_id = {
        expression_id: index for index, expression_id in enumerate(expression_ids)
    }
    expressions = FacialExpression.query.filter(
        FacialExpression.expression_id.in_(expression_ids)
    ).all()
    for expression in expressions:
        expression.sort_index = index_by_id[expression.expression_id]
    db.session.flush()
