from app.app import db


class GestureMotorPosition(db.Model):

    __tablename__ = "gesture_motor_position"

    id = db.Column(db.Integer, primary_key=True)
    position = db.Column(db.Integer, nullable=False)
    motor_name = db.Column(db.Integer, db.ForeignKey("motor.name"), nullable=False)
    gesture_id = db.Column(db.Integer, db.ForeignKey("gesture.id"), nullable=False)
