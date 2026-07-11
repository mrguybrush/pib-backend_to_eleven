import os
from model.program_model import Program
from app.app import app
from typing import Any
from app.app import db
import pib_blockly_client
from service import learning_group_service


def get_all_programs() -> list[Program]:
    """With an active learning group: only that group's programs.
    Without one: everything."""
    active_group_id = learning_group_service.active_group_db_id()
    query = Program.query
    if active_group_id is not None:
        query = query.filter(Program.learning_group_id == active_group_id)
    return query.all()


def get_all_programs_admin() -> list[dict]:
    """Every program regardless of the active group, with its group's
    external (UUID) id - for the "Programme zuordnen" assignment table."""
    programs = Program.query.order_by(Program.name.asc()).all()
    return [_program_admin_dto(program) for program in programs]


def _program_admin_dto(program: Program) -> dict:
    return {
        "programNumber": program.program_number,
        "name": program.name,
        "learningGroupId": learning_group_service.group_db_id_to_external(
            program.learning_group_id
        ),
    }


def set_program_group(program_number: str, group_id: str) -> dict:
    program = get_program(program_number)
    program.learning_group_id = learning_group_service.resolve_group_db_id(group_id)
    db.session.flush()
    return _program_admin_dto(program)


def copy_program_to_group(program_number: str, group_id: str) -> dict:
    target_group_db_id = learning_group_service.resolve_group_db_id(group_id)
    source = get_program(program_number)
    name = _unique_program_name(f"{source.name} (Kopie)")
    program = Program(
        name=name,
        code_visual=source.code_visual,
        learning_group_id=target_group_db_id,
    )
    db.session.add(program)
    db.session.flush()
    _create_empty_python_code_file(program.program_number)
    if source.code_visual and source.code_visual != "{}":
        successful, code_python = pib_blockly_client.code_visual_to_python(
            source.code_visual
        )
        if successful:
            _write_to_python_code_file(program.program_number, code_python)
    return _program_admin_dto(program)


def _unique_program_name(base: str) -> str:
    if not Program.query.filter_by(name=base).first():
        return base
    i = 2
    while True:
        candidate = f"{base} ({i})"
        if not Program.query.filter_by(name=candidate).first():
            return candidate
        i += 1


def get_program(program_number: str) -> Program:
    return Program.query.filter(Program.program_number == program_number).one()


def create_program(program_dto: dict[str, Any]) -> Program:
    program = Program(
        name=program_dto["name"],
        # new programs belong to the currently active learning group
        # (None if no group is active - then they're globally visible)
        learning_group_id=learning_group_service.active_group_db_id(),
    )
    db.session.add(program)
    db.session.flush()
    _create_empty_python_code_file(program.program_number)
    return program


def update_program(program_number: str, program_dto: dict[str, Any]) -> Program:
    program = get_program(program_number)
    program.name = program_dto["name"]
    db.session.flush()
    return program


def delete_program(program_number: str) -> None:
    db.session.delete(get_program(program_number))
    _delete_python_code_file(program_number)
    db.session.flush()


def update_program_code(program_number: str, program_dto: dict[str, Any]) -> None:
    program = get_program(program_number)
    code_visual = program_dto["code_visual"]
    program.code_visual = code_visual
    successful, code_python = pib_blockly_client.code_visual_to_python(code_visual)
    if not successful:
        raise Exception("failed to generate python-code")
    _write_to_python_code_file(program_number, code_python)
    db.session.flush()


def _create_empty_python_code_file(program_number):
    open(_get_code_filepath(program_number), "w").close()


def _write_to_python_code_file(program_number, code_python):
    with open(_get_code_filepath(program_number), "w", encoding="utf-8") as f:
        f.write(code_python)


def _delete_python_code_file(program_number):
    os.remove(_get_code_filepath(program_number))


def _get_code_filepath(program_number):
    return os.path.join(app.config["PYTHON_CODE_DIR"], f"{program_number}.py")
