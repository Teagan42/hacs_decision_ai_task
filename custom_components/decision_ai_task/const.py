"""Constants for the AI Task: Generate Description integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "decision_ai_task"

AI_TASK_DOMAIN: Final = "ai_task"
SERVICE_GENERATE_DESCRIPTION: Final = "generate_description"

ATTR_TASK_NAME: Final = "task_name"
ATTR_PROMPT: Final = "prompt"
ATTR_ENTITIES: Final = "entities"
ATTR_DEVICES: Final = "devices"
ATTR_QUESTIONS: Final = "questions"

ATTR_DESCRIPTION: Final = "description"
ATTR_ANSWERS: Final = "answers"

QUESTION_TYPE: Final = "type"
QUESTION_KEY: Final = "key"
QUESTION_TEXT: Final = "question"
QUESTION_REQUIRED: Final = "required"
QUESTION_OPTIONS: Final = "options"
QUESTION_MULTIPLE: Final = "multiple"
QUESTION_MIN: Final = "min"
QUESTION_MAX: Final = "max"
QUESTION_STEP: Final = "step"

# The structured output always carries the free-form description under this key,
# so a question may not claim it.
RESERVED_KEYS: Final = frozenset({ATTR_DESCRIPTION})

# Attributes that bloat the prompt without telling the model anything about state.
IGNORED_ATTRIBUTES: Final = frozenset(
    {
        "entity_picture",
        "icon",
        "friendly_name",
        "supported_features",
        "supported_color_modes",
        "effect_list",
        "source_list",
        "sound_mode_list",
        "preset_modes",
        "fan_modes",
        "hvac_modes",
        "swing_modes",
        "swing_horizontal_modes",
        "attribution",
        "access_token",
    }
)


class QuestionType(StrEnum):
    """Discriminator for the question union."""

    BOOLEAN = "boolean"
    CHOICE = "choice"
    SCORE = "score"
