from app.app import db


class DefectivePin(db.Model):
    """A physical (bricklet, pin) slot marked as defective (e.g. burned) -
    kept separate from BrickletPin since a defective pin usually has no
    motor assigned (that's the point of marking it), and BrickletPin rows
    only ever exist for actually-wired motor/pin combinations."""

    __tablename__ = "defective_pin"

    id = db.Column(db.Integer, primary_key=True)
    bricklet_id = db.Column(db.Integer, db.ForeignKey("bricklet.id"), nullable=False)
    pin = db.Column(db.Integer, nullable=False)

    __table_args__ = (db.UniqueConstraint("bricklet_id", "pin"),)
