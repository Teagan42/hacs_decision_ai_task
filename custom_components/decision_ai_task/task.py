"""The generate_description AI task: questions, task model and runner."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
import re
from typing import Any

from homeassistant.components.ai_task import (
    AITaskEntity,
    AITaskEntityFeature,
    GenDataTask,
)
from homeassistant.components.ai_task.const import DATA_COMPONENT, DATA_PREFERENCES
from homeassistant.components.conversation import ChatLog
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    llm,
    selector,
)
from homeassistant.helpers.chat_session import async_get_chat_session
from homeassistant.helpers.json import json_dumps
from homeassistant.util import dt as dt_util, slugify
import voluptuous as vol

from .const import (
    ATTR_DESCRIPTION,
    DOMAIN,
    IGNORED_ATTRIBUTES,
    QUESTION_KEY,
    QUESTION_MAX,
    QUESTION_MIN,
    QUESTION_MULTIPLE,
    QUESTION_OPTIONS,
    QUESTION_REQUIRED,
    QUESTION_STEP,
    QUESTION_TEXT,
    QUESTION_TYPE,
    RESERVED_KEYS,
    QuestionType,
)

_KEY_MAX_LENGTH = 48
_HAS_WORD = re.compile(r"[^\W_]")

_BASE_QUESTION = {
    vol.Required(QUESTION_TYPE): vol.Coerce(QuestionType),
    vol.Optional(QUESTION_KEY): cv.slug,
    vol.Required(QUESTION_TEXT): cv.string,
    vol.Optional(QUESTION_REQUIRED, default=True): cv.boolean,
}


def _validate_score_range(value: dict[str, Any]) -> dict[str, Any]:
    if value[QUESTION_MIN] >= value[QUESTION_MAX]:
        raise vol.Invalid("score min must be less than max")
    return value


_QUESTION_SCHEMAS: dict[QuestionType, vol.Schema] = {
    QuestionType.BOOLEAN: vol.Schema(_BASE_QUESTION),
    QuestionType.CHOICE: vol.Schema(
        {
            **_BASE_QUESTION,
            vol.Required(QUESTION_OPTIONS): vol.All(
                cv.ensure_list, [cv.string], vol.Length(min=2), vol.Unique()
            ),
            vol.Optional(QUESTION_MULTIPLE, default=False): cv.boolean,
        }
    ),
    QuestionType.SCORE: vol.All(
        vol.Schema(
            {
                **_BASE_QUESTION,
                vol.Optional(QUESTION_MIN, default=0): vol.Coerce(float),
                vol.Optional(QUESTION_MAX, default=10): vol.Coerce(float),
                vol.Optional(QUESTION_STEP, default=1): vol.All(
                    vol.Coerce(float), vol.Range(min=0, min_included=False)
                ),
            }
        ),
        _validate_score_range,
    ),
}


def _validate_question(value: Any) -> dict[str, Any]:
    """Validate one member of the question union, dispatching on its type."""
    if not isinstance(value, dict):
        raise vol.Invalid("question must be a mapping")
    try:
        question_type = QuestionType(value.get(QUESTION_TYPE))
    except ValueError:
        raise vol.Invalid(
            f"question type must be one of {', '.join(QuestionType)}",
            path=[QUESTION_TYPE],
        ) from None
    return _QUESTION_SCHEMAS[question_type](value)


@dataclass(frozen=True, slots=True)
class Question:
    """A single question the model must answer alongside the description."""

    type: QuestionType
    key: str
    question: str
    required: bool = True
    options: tuple[str, ...] = ()
    multiple: bool = False
    min: float = 0
    max: float = 10
    step: float = 1

    @property
    def selector(self) -> selector.Selector:
        """Return the selector describing a valid answer."""
        if self.type is QuestionType.BOOLEAN:
            return selector.BooleanSelector()
        if self.type is QuestionType.CHOICE:
            return selector.SelectSelector(
                {"options": list(self.options), "multiple": self.multiple}
            )
        return selector.NumberSelector(
            {
                "min": self.min,
                "max": self.max,
                "step": self.step,
                "mode": selector.NumberSelectorMode.BOX,
            }
        )

    @property
    def hint(self) -> str:
        """Return a short human readable description of the answer format."""
        if self.type is QuestionType.BOOLEAN:
            return "true or false"
        if self.type is QuestionType.CHOICE:
            options = ", ".join(json_dumps(option) for option in self.options)
            if self.multiple:
                return f"a list containing any of: {options}"
            return f"exactly one of: {options}"
        return (
            f"a number from {_num(self.min)} to {_num(self.max)}"
            f" in steps of {_num(self.step)}"
        )

    def coerce(self, value: Any) -> Any:
        """Tidy a validated answer (scores on an integer grid become ints)."""
        if self.type is QuestionType.SCORE and _is_integral(
            self.min, self.max, self.step
        ):
            return round(value)
        return value


def _num(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _is_integral(*values: float) -> bool:
    return all(float(value).is_integer() for value in values)


def _finalize_questions(raw: list[dict[str, Any]]) -> list[Question]:
    """Assign keys to questions and turn them into Question objects."""
    explicit = [q[QUESTION_KEY] for q in raw if QUESTION_KEY in q]
    if len(explicit) != len(set(explicit)):
        raise vol.Invalid("question keys must be unique")
    if reserved := RESERVED_KEYS.intersection(explicit):
        raise vol.Invalid(f"question key {sorted(reserved)[0]!r} is reserved")

    taken = set(explicit) | RESERVED_KEYS
    questions: list[Question] = []
    for index, item in enumerate(raw, start=1):
        if (key := item.get(QUESTION_KEY)) is None:
            # slugify() turns text without letters or digits into "unknown".
            text = item[QUESTION_TEXT]
            base = (
                slugify(text)[:_KEY_MAX_LENGTH].strip("_")
                if _HAS_WORD.search(text)
                else ""
            )
            key = base or f"question_{index}"
            suffix = 2
            while key in taken:
                key = f"{base or 'question'}_{suffix}"
                suffix += 1
            taken.add(key)
        questions.append(
            Question(
                type=item[QUESTION_TYPE],
                key=key,
                question=item[QUESTION_TEXT],
                required=item[QUESTION_REQUIRED],
                options=tuple(item.get(QUESTION_OPTIONS, ())),
                multiple=item.get(QUESTION_MULTIPLE, False),
                min=item.get(QUESTION_MIN, 0),
                max=item.get(QUESTION_MAX, 10),
                step=item.get(QUESTION_STEP, 1),
            )
        )
    return questions


QUESTIONS_SCHEMA = vol.All(cv.ensure_list, [_validate_question], _finalize_questions)


def _format_state(state: State) -> dict[str, Any]:
    """Render a state as a compact dict for the prompt."""
    formatted: dict[str, Any] = {
        "entity_id": state.entity_id,
        "name": state.name,
        "state": state.state,
        "last_changed": state.last_changed.isoformat(),
    }
    if attributes := {
        key: value
        for key, value in state.attributes.items()
        if key not in IGNORED_ATTRIBUTES
    }:
        formatted["attributes"] = attributes
    return formatted


@dataclass(slots=True)
class GenDescriptionTask:
    """A generate_description task to be processed by an AI Task entity."""

    name: str
    """Name of the task."""

    prompt: str
    """What the user wants described or decided."""

    states: list[State] = field(default_factory=list)
    """States the description must be based on."""

    questions: list[Question] = field(default_factory=list)
    """Questions to answer alongside the description."""

    llm_api: llm.API | None = None
    """API to provide to the LLM."""

    attachments: None = None
    """Never set; present so core's chat log helper can treat this like its tasks."""

    def __str__(self) -> str:
        """Return task as a string."""
        return f"<GenDescriptionTask {self.name}: {id(self)}>"

    @property
    def instructions(self) -> str:
        """Render the prompt, state context and answer format as instructions."""
        parts = [self.prompt.strip()]
        if self.states:
            parts.append(
                "Base your answer only on the following Home Assistant state, "
                f"captured at {dt_util.utcnow().isoformat()}:\n"
                f"{json_dumps([_format_state(state) for state in self.states])}"
            )
        parts.append(
            f'Put your response to the request above in the "{ATTR_DESCRIPTION}" field.'
        )
        if self.questions:
            lines = [
                f'- "{q.key}" ({q.hint}{"" if q.required else ", optional"}): '
                f"{q.question}"
                for q in self.questions
            ]
            parts.append(
                "Also answer each question in its own field:\n" + "\n".join(lines)
            )
        return "\n\n".join(parts)

    @property
    def structure(self) -> vol.Schema:
        """Return the structured output schema the model must fill in."""
        fields: dict[vol.Marker, selector.Selector] = {
            vol.Required(
                ATTR_DESCRIPTION, description="Response to the request"
            ): selector.TextSelector({"multiline": True}),
        }
        for q in self.questions:
            marker = vol.Required if q.required else vol.Optional
            fields[marker(q.key, description=q.question)] = q.selector
        return vol.Schema(fields, extra=vol.PREVENT_EXTRA)

    def as_gen_data_task(self) -> GenDataTask:
        """Express this task as a core generate_data task."""
        return GenDataTask(
            name=self.name,
            instructions=self.instructions,
            structure=self.structure,
            llm_api=self.llm_api,
        )

    def result_from_data(
        self, conversation_id: str, data: Any
    ) -> GenDescriptionTaskResult:
        """Validate structured model output and build the task result."""
        if not isinstance(data, dict):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unstructured_response",
            )
        try:
            validated = self.structure.extend({}, extra=vol.REMOVE_EXTRA)(data)
        except vol.Invalid as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_response",
                translation_placeholders={"error": str(err)},
            ) from err
        return GenDescriptionTaskResult(
            conversation_id=conversation_id,
            description=validated[ATTR_DESCRIPTION],
            answers={
                q.key: q.coerce(validated[q.key])
                for q in self.questions
                if q.key in validated
            },
        )


@dataclass(slots=True)
class GenDescriptionTaskResult:
    """Result of a generate_description task."""

    conversation_id: str
    """Unique identifier for the conversation."""

    description: str
    """The generated description."""

    answers: dict[str, Any]
    """Answers keyed by question key."""

    def as_dict(self) -> dict[str, Any]:
        """Return result as a dict."""
        return {
            "conversation_id": self.conversation_id,
            "description": self.description,
            "answers": self.answers,
        }


async def _async_generate_description(
    self: AITaskEntity, task: GenDescriptionTask, chat_log: ChatLog
) -> GenDescriptionTaskResult:
    """Handle a gen description task natively.

    Grafted onto AITaskEntity. Providers that want to own this task type override
    it; everyone else gets the task run through their generate_data support.
    """
    raise NotImplementedError


def supports_native_description(entity: AITaskEntity) -> bool:
    """Return True if the entity implements generate_description itself."""
    handler = getattr(type(entity), "_async_generate_description", None)
    return handler is not None and handler is not _async_generate_description


def async_resolve_states(
    hass: HomeAssistant,
    entity_ids: Iterable[str] = (),
    device_ids: Iterable[str] = (),
) -> list[State]:
    """Return the states of the given entities plus every entity of the devices."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    wanted: dict[str, None] = dict.fromkeys(entity_ids)
    for device_id in device_ids:
        if dev_reg.async_get(device_id) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device_id": device_id},
            )
        wanted.update(
            dict.fromkeys(
                entry.entity_id
                for entry in er.async_entries_for_device(ent_reg, device_id)
                if entry.disabled_by is None and hass.states.get(entry.entity_id)
            )
        )

    states: list[State] = []
    for entity_id in wanted:
        if (state := hass.states.get(entity_id)) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entity_not_found",
                translation_placeholders={"entity_id": entity_id},
            )
        states.append(state)
    return states


async def async_generate_description(
    hass: HomeAssistant,
    *,
    task_name: str,
    prompt: str,
    entity_id: str | None = None,
    entities: Sequence[str] = (),
    devices: Sequence[str] = (),
    questions: Sequence[Question] = (),
    llm_api: llm.API | None = None,
) -> GenDescriptionTaskResult:
    """Run a generate_description task in the AI Task integration."""
    if entity_id is None:
        entity_id = hass.data[DATA_PREFERENCES].gen_data_entity_id

    if entity_id is None:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_entity")

    entity: AITaskEntity | None = hass.data[DATA_COMPONENT].get_entity(entity_id)
    if entity is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="entity_missing",
            translation_placeholders={"entity_id": entity_id},
        )

    if (
        not supports_native_description(entity)
        and AITaskEntityFeature.GENERATE_DATA not in entity.supported_features
    ):
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="not_supported",
            translation_placeholders={"entity_id": entity_id},
        )

    task = GenDescriptionTask(
        name=task_name,
        prompt=prompt,
        states=async_resolve_states(hass, entities, devices),
        questions=list(questions),
        llm_api=llm_api,
    )

    with async_get_chat_session(hass) as session:
        return await entity.internal_async_generate_description(  # type: ignore[attr-defined]
            session, task
        )
