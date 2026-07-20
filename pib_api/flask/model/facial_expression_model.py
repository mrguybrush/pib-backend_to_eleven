from app.app import db
from model.util import generate_uuid


class FacialExpression(db.Model):

    __tablename__ = "facial_expression"

    id = db.Column(db.Integer, primary_key=True)
    expression_id = db.Column(
        db.String(255), nullable=False, default=generate_uuid, unique=True
    )
    name = db.Column(db.String(255), nullable=False, unique=True)
    # Drag&Drop-Reihenfolge in der Verwaltungsseite; NULL = noch nie
    # einsortiert (faellt ans Listenende, siehe facial_expression_service)
    sort_index = db.Column(db.Integer, nullable=True)
