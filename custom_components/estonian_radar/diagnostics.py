"""Diagnostics for the Estonian Weather Radar integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import EstonianRadarConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EstonianRadarConfigEntry
) -> dict[str, Any]:
    """Return everything useful for a bug report.

    Coordinates are the only personal data involved, and they are the whole point of
    the integration, so they are rounded rather than redacted — enough to reason about
    radar coverage, not enough to find a front door.
    """
    coordinator = entry.runtime_data
    forecast = coordinator.data
    field = coordinator.source.field

    diagnostics: dict[str, Any] = {
        "options": dict(entry.options),
        "settings": {
            "latitude": round(coordinator.settings.latitude, 2),
            "longitude": round(coordinator.settings.longitude, 2),
            "rain_threshold": coordinator.settings.rain_threshold,
            "window_radius": coordinator.settings.window_radius,
            "forecast_minutes": coordinator.settings.forecast_minutes,
        },
        "last_update_success": coordinator.last_update_success,
    }

    if field is not None:
        geometry = field.latest.geometry
        diagnostics["radar_field"] = {
            "frame_time": field.latest.timestamp.isoformat(),
            "frame_file": field.latest.filename,
            "frame_age_minutes": round(field.frame_age_minutes, 1),
            "motion": asdict(field.motion),
            "grid": {
                "xsize": geometry.xsize,
                "ysize": geometry.ysize,
                "projdef": geometry.projdef,
            },
        }

    if forecast is not None:
        diagnostics["forecast"] = {
            "state": forecast.state,
            "pixel": list(forecast.pixel),
            "raining_now": forecast.raining_now,
            "rain_rate_mm_h": forecast.rain_rate_mm_h,
            "rain_starts_in_minutes": forecast.rain_starts_in_minutes,
            "rain_ends_in_minutes": forecast.rain_ends_in_minutes,
            "series_mm_h": list(forecast.series_mm_h),
            "nearest_radar": forecast.nearest_radar,
            "nearest_radar_km": forecast.nearest_radar_km,
            "coverage": forecast.coverage,
            "has_radar_coverage": forecast.has_radar_coverage,
        }

    return diagnostics
