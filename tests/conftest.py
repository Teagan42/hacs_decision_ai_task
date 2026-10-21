"""Fixtures for AI Task: Generate Description tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from typing import Any

from homeassistant.components.ai_task import (
    AITaskEntity,
    AITaskEntityFeature,
    GenDataTask,
    GenDataTaskResult,
)
from homeassistant.components.conversation import ChatLog
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.decision_ai_task.const import DOMAIN

PROVIDER_DOMAIN = "test_provider"
PROVIDER_ENTITY_ID = "ai_task.test_task_entity"


class MockAITaskEntity(AITaskEntity):
    """Provider that only knows core's generate_data."""

    _attr_name = "Test Task Entity"
    _attr_supported_features = AITaskEntityFeature.GENERATE_DATA

    def __init__(self) -> None:
        """Initialize."""
        self.data_tasks: list[GenDataTask] = []
        self.response: Any = {"description": "All quiet."}

    async def _async_generate_data(
        self, task: GenDataTask, chat_log: ChatLog
    ) -> GenDataTaskResult:
        self.data_tasks.append(task)
        return GenDataTaskResult(
            conversation_id=chat_log.conversation_id, data=self.response
        )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations."""


@pytest.fixture
def provider_entity() -> MockAITaskEntity:
    """Provider entity under test; tests may swap the class."""
    return MockAITaskEntity()


@pytest.fixture
def provider_config_flow() -> Generator[None]:
    """Register a do-nothing config flow for the fake provider."""
    with mock_config_flow(PROVIDER_DOMAIN, ConfigFlow):
        yield


@pytest.fixture
async def provider(
    hass: HomeAssistant,
    provider_entity: MockAITaskEntity,
    provider_config_flow: None,
) -> MockAITaskEntity:
    """Set up a fake AI Task provider integration."""
    assert await async_setup_component(hass, "homeassistant", {})

    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        await hass.config_entries.async_forward_entry_setups(entry, ["ai_task"])
        return True

    async def async_setup_entry_platform(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        async_add_entities([provider_entity])

    mock_integration(
        hass, MockModule(PROVIDER_DOMAIN, async_setup_entry=async_setup_entry)
    )
    mock_platform(hass, f"{PROVIDER_DOMAIN}.config_flow")
    mock_platform(
        hass,
        f"{PROVIDER_DOMAIN}.ai_task",
        MockPlatform(async_setup_entry=async_setup_entry_platform),
    )
    entry = MockConfigEntry(domain=PROVIDER_DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return provider_entity


@pytest.fixture
async def integration(
    hass: HomeAssistant, provider: MockAITaskEntity
) -> AsyncGenerator[MockConfigEntry]:
    """Set up this integration on top of the provider."""
    entry = MockConfigEntry(domain=DOMAIN, title="AI Task: Generate Description")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    if entry.state.recoverable:
        await hass.config_entries.async_unload(entry.entry_id)
