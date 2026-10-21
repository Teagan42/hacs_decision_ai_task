"""Monkey patches that graft generate_description onto core's ai_task.

ai_task is owned by core, so there is no extension point for a new task type.
Three things get patched while the config entry is loaded:

* AITaskEntity gains ``internal_async_generate_description`` (the task entry
  point) and an overridable ``_async_generate_description`` hook.
* Translation loading merges this integration's ``services`` and ``selector``
  strings into ``component.ai_task`` so the action is localized like core's own.
* Icon loading merges this integration's service icons into ``ai_task``.

Everything is reverted on unload. The translation/icon patches poke private
helpers; if a future core release moves them, they are skipped with a warning
and the action still works (it just falls back to untranslated text).
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.components.ai_task import AITaskEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import icon, translation
from homeassistant.helpers.chat_session import ChatSession
from homeassistant.loader import Integration, async_get_integration
from homeassistant.util import dt as dt_util

from .const import AI_TASK_DOMAIN, DOMAIN
from .task import (
    GenDescriptionTask,
    GenDescriptionTaskResult,
    _async_generate_description,
    supports_native_description,
)

_LOGGER = logging.getLogger(__name__)

# Sections of our strings.json / icons.json that belong to ai_task.
_TRANSLATION_SECTIONS = ("services", "selector")
_ICON_SECTIONS = ("services",)

# Name-mangled private attribute behind AITaskEntity.state.
_LAST_ACTIVITY_ATTR = "_AITaskEntity__last_activity"


async def internal_async_generate_description(
    self: AITaskEntity,
    session: ChatSession,
    task: GenDescriptionTask,
) -> GenDescriptionTaskResult:
    """Run a gen description task (grafted onto AITaskEntity)."""
    if not supports_native_description(self):
        result = await self.internal_async_generate_data(
            session, task.as_gen_data_task()
        )
        return task.result_from_data(result.conversation_id, result.data)

    setattr(self, _LAST_ACTIVITY_ATTR, dt_util.utcnow().isoformat())
    self.async_write_ha_state()
    # The core helper only reads .instructions/.attachments, which the task has.
    async with self._async_get_ai_task_chat_log(session, task) as chat_log:  # type: ignore[arg-type]
        return await self._async_generate_description(task, chat_log)  # type: ignore[attr-defined]


def _merge_sections(
    target: dict[str, Any], source: dict[str, Any], sections: tuple[str, ...]
) -> None:
    for section in sections:
        if section in source:
            target.setdefault(section, {}).update(source[section])


async def _with_our_integration(
    hass: HomeAssistant,
    components: set[str],
    integrations: dict[str, Integration],
) -> tuple[set[str], dict[str, Integration], bool]:
    """Add this integration to a load request; report whether it was added."""
    if DOMAIN in components:
        return components, integrations, False
    ours = await async_get_integration(hass, DOMAIN)
    return components | {DOMAIN}, {**integrations, DOMAIN: ours}, True


def _patch_translations(hass: HomeAssistant) -> Callable[[], None]:
    original = translation._async_get_component_strings

    async def _async_get_component_strings(
        hass: HomeAssistant,
        languages: Any,
        components: set[str],
        integrations: dict[str, Integration],
    ) -> dict[str, dict[str, Any]]:
        if AI_TASK_DOMAIN not in components:
            return await original(hass, languages, components, integrations)
        components, integrations, added = await _with_our_integration(
            hass, components, integrations
        )
        result = await original(hass, languages, components, integrations)
        for by_component in result.values():
            ours = (by_component.pop if added else by_component.get)(DOMAIN, {})
            _merge_sections(
                by_component.setdefault(AI_TASK_DOMAIN, {}), ours, _TRANSLATION_SECTIONS
            )
        return result

    translation._async_get_component_strings = _async_get_component_strings

    def undo() -> None:
        translation._async_get_component_strings = original

    return undo


def _patch_icons(hass: HomeAssistant) -> Callable[[], None]:
    original = icon._async_get_component_icons

    async def _async_get_component_icons(
        hass: HomeAssistant,
        components: set[str],
        integrations: dict[str, Integration],
    ) -> dict[str, Any]:
        if AI_TASK_DOMAIN not in components:
            return await original(hass, components, integrations)
        components, integrations, added = await _with_our_integration(
            hass, components, integrations
        )
        result = await original(hass, components, integrations)
        ours = (result.pop if added else result.get)(DOMAIN, {})
        _merge_sections(result.setdefault(AI_TASK_DOMAIN, {}), ours, _ICON_SECTIONS)
        return result

    icon._async_get_component_icons = _async_get_component_icons

    def undo() -> None:
        icon._async_get_component_icons = original

    return undo


def _patch_entity() -> Callable[[], None]:
    AITaskEntity.internal_async_generate_description = (  # type: ignore[attr-defined]
        internal_async_generate_description
    )
    AITaskEntity._async_generate_description = _async_generate_description  # type: ignore[attr-defined]

    def undo() -> None:
        del AITaskEntity.internal_async_generate_description  # type: ignore[attr-defined]
        del AITaskEntity._async_generate_description  # type: ignore[attr-defined]

    return undo


@callback
def _invalidate_caches(hass: HomeAssistant) -> None:
    """Make core reload ai_task strings and icons through the (un)patched loaders."""
    cache = translation._async_get_translations_cache(hass)
    for loaded in cache.cache_data.loaded.values():
        loaded.discard(AI_TASK_DOMAIN)
    if icon_cache := hass.data.get(icon.ICON_CACHE):
        icon_cache._loaded.discard(AI_TASK_DOMAIN)


@callback
def async_apply(hass: HomeAssistant) -> Callable[[], None]:
    """Apply all patches and return a callback that reverts them."""
    if hasattr(AITaskEntity, "internal_async_generate_description"):
        raise RuntimeError(f"{DOMAIN} patches are already applied")

    undos = [_patch_entity()]
    for name, patcher in (
        ("translations", _patch_translations),
        ("icons", _patch_icons),
    ):
        try:
            undos.append(patcher(hass))
        except AttributeError:
            _LOGGER.warning(
                "Core %s internals changed; generate_description %s are unavailable",
                name,
                name,
            )
    try:
        _invalidate_caches(hass)
    except AttributeError:
        _LOGGER.debug("Could not invalidate translation/icon caches", exc_info=True)

    @callback
    def async_revert() -> None:
        for undo in reversed(undos):
            undo()
        try:
            _invalidate_caches(hass)
        except AttributeError:
            _LOGGER.debug("Could not invalidate translation/icon caches", exc_info=True)

    return async_revert
