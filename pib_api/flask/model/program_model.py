from app.app import db

from model.util import generate_uuid


class Program(db.Model):
    __tablename__ = "program"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    code_visual = db.Column(db.String(100000), nullable=False, default="{}")
    program_number = db.Column(
        db.String(50), unique=True, nullable=False, default=generate_uuid
    )
    # None = not assigned to any learning group (visible only when no
    # group is active) - see learning_group_model.py
    learning_group_id = db.Column(
        db.Integer, db.ForeignKey("learning_group.id"), nullable=True
    )
