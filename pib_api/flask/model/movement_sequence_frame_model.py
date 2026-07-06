from app.app import db


class MovementSequenceFrame(db.Model):

    __tablename__ = "movement_sequence_frame"

    id = db.Column(db.Integer, primary_key=True)
    frame_index = db.Column(db.Integer, nullable=False)
    timestamp_ms = db.Column(db.Integer, nullable=False)
    # {motor_name: position, ...} - JSON so new motors don't need a migration
    positions = db.Column(db.JSON, nullable=False)
    sequence_id = db.Column(
        db.Integer, db.ForeignKey("movement_sequence.id"), nullable=False
    )
