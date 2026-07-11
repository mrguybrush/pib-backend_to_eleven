from typing import List
from model.assistant_model import AssistantModel


def get_all_assistant_models() -> List[AssistantModel]:
    # No filtering: an old exclusion of "gemini-2.5-flash" (hidden while the
    # Gemini integration wasn't user-facing yet) silently broke the Settings
    # page's Gemini radio button - the frontend could not find the Gemini
    # model id in this list, so selecting Gemini never assigned it to any
    # personality and the choice appeared to "not save".
    return AssistantModel.query.all()


def get_assistant_model_by_id(assistant_model_id: int) -> AssistantModel:
    return AssistantModel.query.filter_by(id=assistant_model_id).first()
