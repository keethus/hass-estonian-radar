"""The Estonian Weather Radar integration.

Short-term (nowcast) precipitation forecasts for a point, derived from the Estonian
Environment Agency's multi-radar composite.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import EstonianRadarConfigEntry, LocationCoordinator, RadarSource

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: EstonianRadarConfigEntry) -> bool:
    """Set up one configured location."""
    source: RadarSource = hass.data.setdefault(DOMAIN, {}).setdefault(
        "source", RadarSource(hass)
    )

    coordinator = LocationCoordinator(hass, entry, source)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EstonianRadarConfigEntry) -> bool:
    """Tear down one configured location."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        # This entry is still listed as loaded while its own teardown runs, so it has to
        # be excluded before deciding whether it was the last one.
        remaining = [
            other
            for other in hass.config_entries.async_loaded_entries(DOMAIN)
            if other.entry_id != entry.entry_id
        ]
        if not remaining:
            hass.data.pop(DOMAIN, None)

    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: EstonianRadarConfigEntry) -> None:
    """Apply changed options by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
