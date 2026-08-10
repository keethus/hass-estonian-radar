"""Sensor entities for the Estonian Weather Radar integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfSpeed,
    UnitOfTime,
    UnitOfVolumetricFlux,
)
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    async_get_current_platform,
)

from .const import (
    COVERAGE_STATES,
    DOMAIN,
    RAIN_STATES,
    SERVICE_GET_FORECAST,
    SEVERITY_STATES,
)
from .coordinator import EstonianRadarConfigEntry, LocationCoordinator
from .entity import EstonianRadarEntity
from .radar.models import LocationForecast

PRECIPITATION_INTENSITY = UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR


@dataclass(frozen=True, kw_only=True)
class EstonianRadarSensorDescription(SensorEntityDescription):
    """Describes one sensor, including how to read it off a forecast."""

    value_fn: Callable[[LocationForecast], Any]
    attributes_fn: Callable[[LocationForecast], dict[str, Any]] | None = None


def _event_value(attribute: str) -> Callable[[LocationForecast], Any]:
    def getter(forecast: LocationForecast) -> Any:
        return getattr(forecast.event, attribute) if forecast.event else None

    return getter


SENSORS: tuple[EstonianRadarSensorDescription, ...] = (
    EstonianRadarSensorDescription(
        key="rain_state",
        translation_key="rain_state",
        device_class=SensorDeviceClass.ENUM,
        options=RAIN_STATES,
        value_fn=lambda forecast: forecast.state,
    ),
    EstonianRadarSensorDescription(
        key="rain_rate",
        translation_key="rain_rate",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        native_unit_of_measurement=PRECIPITATION_INTENSITY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda forecast: forecast.rain_rate_mm_h,
        attributes_fn=lambda forecast: {
            "forecast": forecast.series_with_time(),
            "step_minutes": forecast.step_minutes,
            "usable_forecast_minutes": forecast.usable_forecast_minutes,
        },
    ),
    EstonianRadarSensorDescription(
        key="rain_starts_in",
        translation_key="rain_starts_in",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda forecast: forecast.rain_starts_in_minutes,
    ),
    EstonianRadarSensorDescription(
        key="rain_ends_in",
        translation_key="rain_ends_in",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda forecast: forecast.rain_ends_in_minutes,
    ),
    EstonianRadarSensorDescription(
        key="expected_severity",
        translation_key="expected_severity",
        device_class=SensorDeviceClass.ENUM,
        options=SEVERITY_STATES,
        value_fn=_event_value("severity"),
    ),
    EstonianRadarSensorDescription(
        key="expected_total",
        translation_key="expected_total",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        suggested_display_precision=1,
        value_fn=_event_value("total_mm"),
    ),
    EstonianRadarSensorDescription(
        key="expected_peak",
        translation_key="expected_peak",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        native_unit_of_measurement=PRECIPITATION_INTENSITY,
        suggested_display_precision=1,
        value_fn=_event_value("peak_mm_h"),
    ),
    EstonianRadarSensorDescription(
        key="expected_duration",
        translation_key="expected_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_event_value("duration_minutes"),
    ),
    # --- diagnostics -----------------------------------------------------------------
    EstonianRadarSensorDescription(
        key="radar_frame_time",
        translation_key="radar_frame_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda forecast: forecast.frame_time,
    ),
    EstonianRadarSensorDescription(
        key="radar_frame_age",
        translation_key="radar_frame_age",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda forecast: forecast.frame_age_minutes,
    ),
    EstonianRadarSensorDescription(
        key="nearest_radar_distance",
        translation_key="nearest_radar_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda forecast: forecast.nearest_radar_km,
        attributes_fn=lambda forecast: {
            "nearest_radar": forecast.nearest_radar,
            "coverage_quality": forecast.coverage,
        },
    ),
    EstonianRadarSensorDescription(
        key="coverage_quality",
        translation_key="coverage_quality",
        device_class=SensorDeviceClass.ENUM,
        options=COVERAGE_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda forecast: forecast.coverage,
    ),
    EstonianRadarSensorDescription(
        key="usable_forecast",
        translation_key="usable_forecast",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda forecast: forecast.usable_forecast_minutes,
    ),
    EstonianRadarSensorDescription(
        key="storm_speed",
        translation_key="storm_speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
        value_fn=lambda forecast: forecast.motion_kmh,
        attributes_fn=lambda forecast: {
            "bearing": forecast.motion_bearing,
            "confidence": round(forecast.motion.confidence, 4),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EstonianRadarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors and the forecast action."""
    coordinator = entry.runtime_data

    async_get_current_platform().async_register_entity_service(
        SERVICE_GET_FORECAST,
        None,
        "async_get_forecast",
        supports_response=SupportsResponse.ONLY,
    )

    async_add_entities(
        EstonianRadarSensor(coordinator, description) for description in SENSORS
    )


class EstonianRadarSensor(EstonianRadarEntity, SensorEntity):
    """A single value read off the location forecast."""

    entity_description: EstonianRadarSensorDescription

    #: The point forecast is 18 values that change every five minutes, and the motion
    #: confidence changes on every update too. Keeping both out of the recorder means
    #: they stay available to templates and charts without writing a new attributes row
    #: to the database each time.
    _unrecorded_attributes = frozenset({"forecast", "confidence"})

    def __init__(
        self,
        coordinator: LocationCoordinator,
        description: EstonianRadarSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if (forecast := self.forecast) is None:
            return None
        return self.entity_description.value_fn(forecast)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        forecast = self.forecast
        if forecast is None or self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(forecast)

    async def async_get_forecast(self) -> dict[str, Any]:
        """Return the point forecast as service response data."""
        if (forecast := self.forecast) is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_forecast")
        return {
            "location": self.coordinator.config_entry.title,
            "frame_time": forecast.frame_time.isoformat(),
            "step_minutes": forecast.step_minutes,
            "coverage_quality": forecast.coverage,
            "forecast": forecast.series_with_time(),
        }
