from app.app import db
from model.util import generate_uuid


class MovementSequence(db.Model):

    __tablename__ = "movement_sequence"

    id = db.Column(db.Integer, primary_key=True)
    sequence_id = db.Column(
        db.String(255), nullable=False, default=generate_uuid, unique=True
    )
    name = db.Column(db.String(255), nullable=False, unique=True)
    deletable = db.Column(db.Boolean, nullable=False, default=True)
    sample_rate_hz = db.Column(db.Float, nullable=False, default=10.0)
    frames = db.relationship(
        "MovementSequenceFrame",
        backref="movement_sequence",
        lazy=True,
        order_by="MovementSequenceFrame.frame_index",
        cascade="all, delete-orphan",
    )
