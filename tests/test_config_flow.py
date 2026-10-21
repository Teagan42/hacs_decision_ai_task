"""Tests for the config flow."""

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.decision_ai_task.const import DOMAIN


async def test_user_flow(hass: HomeAssistant) -> None:
    """The flow is a single confirmation step and the entry loads."""
    assert await async_setup_component(hass, "homeassistant", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {}
    await hass.async_block_till_done()
    assert result["result"].state is ConfigEntryState.LOADED
    assert hass.services.has_service("ai_task", "generate_description")
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_single_instance(hass: HomeAssistant) -> None:
    """Only one entry may exist."""
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
