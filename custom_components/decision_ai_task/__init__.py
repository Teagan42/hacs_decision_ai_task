"""AI Task: Generate Description.

Adds an ``ai_task.generate_description`` action to core's AI Task integration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HassJobType,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv, translation
from homeassistant.helpers.service import async_set_service_schema
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.yaml import load_yaml_dict
import voluptuous as vol

from .const import (
    AI_TASK_DOMAIN,
    ATTR_DEVICES,
    ATTR_ENTITIES,
    ATTR_PROMPT,
    ATTR_QUESTIONS,
    ATTR_TASK_NAME,
    DOMAIN,
    SERVICE_GENERATE_DESCRIPTION,
    QuestionType,
)
from .patch import async_apply as async_apply_patches
from .task import (
    QUESTIONS_SCHEMA,
    GenDescriptionTask,
    GenDescriptionTaskResult,
    Question,
    async_generate_description,
)

__all__ = [
    "DOMAIN",
    "QUESTIONS_SCHEMA",
    "GenDescriptionTask",
    "GenDescriptionTaskResult",
    "Question",
    "QuestionType",
    "async_generate_description",
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TASK_NAME): cv.string,
        vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_PROMPT): cv.string,
        vol.Optional(ATTR_ENTITIES, default=list): cv.entity_ids,
        vol.Optional(ATTR_DEVICES, default=list): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_QUESTIONS, default=list): QUESTIONS_SCHEMA,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Graft generate_description onto ai_task."""
    entry.async_on_unload(async_apply_patches(hass))

    hass.services.async_register(
        AI_TASK_DOMAIN,
        SERVICE_GENERATE_DESCRIPTION,
        _async_service_generate_description,
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
        job_type=HassJobType.Coroutinefunction,
    )
    entry.async_on_unload(
        lambda: hass.services.async_remove(AI_TASK_DOMAIN, SERVICE_GENERATE_DESCRIPTION)
    )
    async_set_service_schema(
        hass,
        AI_TASK_DOMAIN,
        SERVICE_GENERATE_DESCRIPTION,
        await _async_service_description(hass),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry; the unload callbacks revert everything."""
    return True


async def _async_service_generate_description(call: ServiceCall) -> ServiceResponse:
    """Run the generate_description action."""
    result = await async_generate_description(hass=call.hass, **call.data)
    return result.as_dict()


async def _async_service_description(hass: HomeAssistant) -> dict[str, Any]:
    """Build the action description from our services.yaml and strings.

    Core only reads services.yaml from the integration that owns the domain, so
    the description for an action in the ai_task domain must be set by hand.
    """
    services = await hass.async_add_executor_job(
        load_yaml_dict, str(Path(__file__).parent / "services.yaml")
    )
    description: dict[str, Any] = dict(services[SERVICE_GENERATE_DESCRIPTION])
    strings = await translation.async_get_translations(
        hass, hass.config.language, "services", [DOMAIN]
    )
    prefix = f"component.{DOMAIN}.services.{SERVICE_GENERATE_DESCRIPTION}"
    description["name"] = strings.get(f"{prefix}.name", SERVICE_GENERATE_DESCRIPTION)
    description["description"] = strings.get(f"{prefix}.description", "")
    return description
