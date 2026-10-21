"""Config flow for AI Task: Generate Description."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class DecisionAITaskConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-step flow; there is nothing to configure."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm installation."""
        if user_input is not None:
            return self.async_create_entry(
                title="AI Task: Generate Description", data={}
            )
        return self.async_show_form(step_id="user")
