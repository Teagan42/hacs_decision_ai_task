"""Tests for the generate_description action."""

from __future__ import annotations

from typing import Any

from homeassistant.components.ai_task import AITaskEntity
from homeassistant.components.conversation import ChatLog
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    icon,
    translation,
)
from homeassistant.helpers.service import async_get_all_descriptions
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.decision_ai_task import QUESTIONS_SCHEMA
from custom_components.decision_ai_task.task import (
    GenDescriptionTask,
    GenDescriptionTaskResult,
)

from .conftest import PROVIDER_ENTITY_ID, MockAITaskEntity


async def _call(hass: HomeAssistant, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        "ai_task",
        "generate_description",
        {"task_name": "test", "entity_id": PROVIDER_ENTITY_ID, **data},
        blocking=True,
        return_response=True,
    )


async def test_service_lifecycle(
    hass: HomeAssistant, integration: MockConfigEntry
) -> None:
    """The action lives in the ai_task domain only while the entry is loaded."""
    assert hass.services.has_service("ai_task", "generate_description")
    assert hasattr(AITaskEntity, "internal_async_generate_description")

    descriptions = await async_get_all_descriptions(hass)
    description = descriptions["ai_task"]["generate_description"]
    assert description["name"] == "Generate description"
    assert set(description["fields"]) == {
        "task_name",
        "prompt",
        "entity_id",
        "entities",
        "devices",
        "questions",
    }
    assert description["response"] == {"optional": False}
    # Core's own actions are untouched.
    assert "generate_data" in descriptions["ai_task"]

    await hass.config_entries.async_unload(integration.entry_id)
    assert integration.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service("ai_task", "generate_description")
    assert not hasattr(AITaskEntity, "internal_async_generate_description")


async def test_translations_and_icons_merged(
    hass: HomeAssistant, integration: MockConfigEntry
) -> None:
    """Our strings and icons show up under component.ai_task."""
    strings = await translation.async_get_translations(
        hass, "en", "services", ["ai_task"]
    )
    assert (
        strings["component.ai_task.services.generate_description.name"]
        == "Generate description"
    )
    # Core's strings survive the merge.
    assert "component.ai_task.services.generate_data.name" in strings

    selectors = await translation.async_get_translations(
        hass, "en", "selector", ["ai_task"]
    )
    assert (
        selectors["component.ai_task.selector.description_question_type.options.score"]
        == "Score"
    )

    icons = await icon.async_get_icons(hass, "services", ["ai_task"])
    assert icons["ai_task"]["generate_description"] == {
        "service": "mdi:text-box-search-outline"
    }
    assert "generate_data" in icons["ai_task"]

    # Our domain must not leak in when it was not asked for.
    assert not any(k.startswith("component.decision_ai_task") for k in strings)


async def test_generate_description(
    hass: HomeAssistant, integration: MockConfigEntry, provider: MockAITaskEntity
) -> None:
    """Prompt, states and questions reach the provider; answers come back."""
    hass.states.async_set(
        "lock.front_door", "unlocked", {"friendly_name": "Front door"}
    )
    hass.states.async_set(
        "sensor.temp",
        "19.5",
        {"unit_of_measurement": "°C", "entity_picture": "/x.png"},
    )
    provider.response = {
        "description": "The front door is unlocked.",
        "secure": False,
        "priority": "doors",
        "readiness": 3.0,
        "made_up": "ignored",
    }

    result = await _call(
        hass,
        prompt="Is the house ready for bed?",
        entities=["lock.front_door", "sensor.temp"],
        questions=[
            {"type": "boolean", "key": "secure", "question": "Is it secure?"},
            {
                "type": "choice",
                "key": "priority",
                "question": "What first?",
                "options": ["doors", "lights"],
            },
            {"type": "score", "key": "readiness", "question": "How ready?"},
        ],
    )

    assert result["description"] == "The front door is unlocked."
    assert result["answers"] == {"secure": False, "priority": "doors", "readiness": 3}
    assert isinstance(result["answers"]["readiness"], int)
    assert result["conversation_id"]

    (task,) = provider.data_tasks
    assert task.name == "test"
    assert task.instructions.startswith("Is the house ready for bed?")
    assert '"entity_id":"lock.front_door"' in task.instructions
    assert '"state":"unlocked"' in task.instructions
    assert '"unit_of_measurement":"°C"' in task.instructions
    assert "entity_picture" not in task.instructions
    assert '- "readiness" (a number from 0 to 10 in steps of 1): How ready?' in (
        task.instructions
    )
    assert list(task.structure.schema) == [
        "description",
        "secure",
        "priority",
        "readiness",
    ]
    assert hass.states.get(PROVIDER_ENTITY_ID).state not in (None, "unknown")


async def test_devices_expand_to_entities(
    hass: HomeAssistant, integration: MockConfigEntry, provider: MockAITaskEntity
) -> None:
    """A device contributes the states of all its enabled entities."""
    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={("test", "garage")}
    )
    ent_reg = er.async_get(hass)
    door = ent_reg.async_get_or_create(
        "cover", "test", "door", device_id=device.id, config_entry=config_entry
    )
    disabled = ent_reg.async_get_or_create(
        "sensor",
        "test",
        "battery",
        device_id=device.id,
        config_entry=config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    hass.states.async_set(door.entity_id, "open")
    hass.states.async_set(disabled.entity_id, "80")

    await _call(hass, prompt="Describe the garage.", devices=[device.id])

    instructions = provider.data_tasks[0].instructions
    assert door.entity_id in instructions
    assert disabled.entity_id not in instructions


async def test_missing_entity_or_device(
    hass: HomeAssistant, integration: MockConfigEntry
) -> None:
    """Asking about things that do not exist fails loudly."""
    with pytest.raises(ServiceValidationError, match=r"light\.nope"):
        await _call(hass, prompt="x", entities=["light.nope"])
    with pytest.raises(ServiceValidationError, match="abc123"):
        await _call(hass, prompt="x", devices=["abc123"])


async def test_invalid_model_output(
    hass: HomeAssistant, integration: MockConfigEntry, provider: MockAITaskEntity
) -> None:
    """Answers outside the question's constraints are rejected."""
    provider.response = {"description": "x", "score": 42}
    with pytest.raises(HomeAssistantError, match="does not match the questions"):
        await _call(
            hass,
            prompt="x",
            questions=[{"type": "score", "key": "score", "question": "?"}],
        )

    provider.response = "plain text"
    with pytest.raises(HomeAssistantError, match="did not return structured data"):
        await _call(hass, prompt="x")


async def test_preferred_entity(
    hass: HomeAssistant, integration: MockConfigEntry, provider: MockAITaskEntity
) -> None:
    """Without entity_id the preferred generate_data entity is used."""
    with pytest.raises(HomeAssistantError, match="no preferred"):
        await hass.services.async_call(
            "ai_task",
            "generate_description",
            {"task_name": "t", "prompt": "x"},
            blocking=True,
            return_response=True,
        )

    hass.data["ai_task_preferences"].async_set_preferences(
        gen_data_entity_id=PROVIDER_ENTITY_ID
    )
    result = await hass.services.async_call(
        "ai_task",
        "generate_description",
        {"task_name": "t", "prompt": "x"},
        blocking=True,
        return_response=True,
    )
    assert result["description"] == "All quiet."


class NativeAITaskEntity(MockAITaskEntity):
    """Provider that implements generate_description itself."""

    _attr_supported_features = 0

    async def _async_generate_description(
        self, task: GenDescriptionTask, chat_log: ChatLog
    ) -> GenDescriptionTaskResult:
        self.native_instructions = chat_log.content[-1].content
        return task.result_from_data(
            chat_log.conversation_id, {"description": "native", "ok": True}
        )


@pytest.mark.parametrize("provider_entity", [NativeAITaskEntity()])
async def test_native_provider(
    hass: HomeAssistant, integration: MockConfigEntry, provider: NativeAITaskEntity
) -> None:
    """Providers overriding the hook skip the generate_data fallback."""
    result = await _call(
        hass,
        prompt="Native please",
        questions=[{"type": "boolean", "key": "ok", "question": "OK?"}],
    )
    assert result["description"] == "native"
    assert result["answers"] == {"ok": True}
    assert provider.data_tasks == []
    assert provider.native_instructions.startswith("Native please")
    assert hass.states.get(PROVIDER_ENTITY_ID).state not in (None, "unknown")


@pytest.mark.parametrize(
    ("questions", "error"),
    [
        ([{"type": "rating", "question": "?"}], "question type must be one of"),
        ([{"type": "choice", "question": "?", "options": ["only"]}], "length"),
        ([{"type": "boolean", "question": "?", "options": ["a", "b"]}], "extra keys"),
        ([{"type": "score", "question": "?", "min": 5, "max": 5}], "min must be less"),
        ([{"type": "score", "question": "?", "step": 0}], "value must be"),
        (
            [
                {"type": "boolean", "key": "a", "question": "?"},
                {"type": "boolean", "key": "a", "question": "!"},
            ],
            "unique",
        ),
        ([{"type": "boolean", "key": "description", "question": "?"}], "reserved"),
    ],
)
def test_question_validation(questions: list[dict[str, Any]], error: str) -> None:
    """The question union rejects malformed members."""
    with pytest.raises(vol.Invalid, match=error):
        QUESTIONS_SCHEMA(questions)


def test_question_keys_derived() -> None:
    """Missing keys come from the question text and never collide."""
    questions = QUESTIONS_SCHEMA(
        [
            {"type": "boolean", "question": "Is it on?"},
            {"type": "boolean", "question": "Is it on?"},
            {"type": "boolean", "key": "is_it_on_3", "question": "x"},
            {"type": "boolean", "question": "Is it on?"},
            {"type": "boolean", "question": "???"},
            {"type": "boolean", "question": "Description"},
        ]
    )
    assert [q.key for q in questions] == [
        "is_it_on",
        "is_it_on_2",
        "is_it_on_3",
        "is_it_on_4",
        "question_5",
        "description_2",
    ]
