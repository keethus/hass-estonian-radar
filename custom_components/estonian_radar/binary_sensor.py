"""Binary sensors for the Estonian Weather Radar integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EstonianRadarConfigEntry, LocationCoordinator
from .entity import EstonianRadarEntity
from .radar.const import COVERAGE_OUT_OF_RANGE, MAX_FRAME_AGE_MINUTES
from .radar.models import LocationForecast


@dataclass(frozen=True, kw_only=True)
class EstonianRadarBinarySensorDescription(BinarySensorEntityDescription):
    """Describes one binary sensor."""

    value_fn: Callable[[LocationForecast], bool]


def _has_problem(forecast: LocationForecast) -> bool:
    """True when the reading should not be trusted.

    A location the radar cannot see must never read as "dry" — that is the difference
    between "we looked and it is not raining" and "we did not look".
    """
    return (
        not forecast.has_radar_coverage
        or forecast.coverage == COVERAGE_OUT_OF_RANGE
        or forecast.frame_age_minutes > MAX_FRAME_AGE_MINUTES
    )


BINARY_SENSORS: tuple[EstonianRadarBinarySensorDescription, ...] = (
    EstonianRadarBinarySensorDescription(
        key="raining",
        translation_key="raining",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda forecast: forecast.raining_now,
    ),
    EstonianRadarBinarySensorDescription(
        key="rain_expected",
        translation_key="rain_expected",
        value_fn=lambda forecast: forecast.rain_starts_in_minutes is not None,
    ),
    EstonianRadarBinarySensorDescription(
        key="data_problem",
        translation_key="data_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_has_problem,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EstonianRadarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        EstonianRadarBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class EstonianRadarBinarySensor(EstonianRadarEntity, BinarySensorEntity):
    """A boolean read off the location forecast."""

    entity_description: EstonianRadarBinarySensorDescription

    def __init__(
        self,
        coordinator: LocationCoordinator,
        description: EstonianRadarBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if (forecast := self.forecast) is None:
            return None
        return self.entity_description.value_fn(forecast)
