"""Shared entity base for the Estonian Weather Radar integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONFIGURATION_URL, DOMAIN, MANUFACTURER, MODEL
from .coordinator import LocationCoordinator


class EstonianRadarEntity(CoordinatorEntity[LocationCoordinator]):
    """Base entity.

    ``_attr_has_entity_name`` means the visible name is composed from the device name
    (whatever the user called this location) and a translated entity name, so nothing
    in this repository hard-codes a place name or a language.
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: LocationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=CONFIGURATION_URL,
        )

    @property
    def forecast(self):
        return self.coordinator.data

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None
