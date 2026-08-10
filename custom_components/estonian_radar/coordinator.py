"""Data fetching for the Estonian Weather Radar integration.

Two layers, because their costs differ by orders of magnitude:

``RadarSource``
    One per Home Assistant instance. Downloads and decodes the composite and estimates
    storm motion — seconds of work, so it happens once no matter how many locations
    are configured.

``LocationCoordinator``
    One per config entry. Turns the shared field into a forecast for its coordinates,
    which is a handful of array slices.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_FORECAST_MINUTES,
    CONF_RAIN_THRESHOLD,
    CONF_WINDOW_RADIUS,
    DOMAIN,
    EVENT_RAIN_EXPECTED,
    EVENT_RAIN_STARTED,
    EVENT_RAIN_STOPPED,
    SOURCE_CACHE_SECONDS,
    UPDATE_INTERVAL,
)
from .radar import (
    KaiaClient,
    KaiaError,
    NoRadarData,
    build_field,
    decode_latest_frames,
    forecast_location,
)
from .radar.const import (
    DEFAULT_FORECAST_MINUTES,
    DEFAULT_RAIN_THRESHOLD_MM_H,
    DEFAULT_WINDOW_RADIUS_PX,
    MAX_FRAME_AGE_MINUTES,
)
from .radar.models import LocationForecast, NowcastField

_LOGGER = logging.getLogger(__name__)

type EstonianRadarConfigEntry = ConfigEntry[LocationCoordinator]


class RadarSource:
    """Shared, cached access to the decoded radar field."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._client = KaiaClient(async_get_clientsession(hass))
        self._field: NowcastField | None = None
        self._lock = asyncio.Lock()

    @property
    def field(self) -> NowcastField | None:
        """Last successfully built field, if any."""
        return self._field

    async def async_get_field(self) -> NowcastField:
        """Return a recent radar field, downloading a new one only when stale.

        Concurrent callers wait on the same lock, so five apartments configured in one
        Home Assistant still cause exactly one download.
        """
        async with self._lock:
            if self._is_fresh():
                assert self._field is not None
                return self._field

            archives = await self._client.async_fetch_archives()
            frames = await self._hass.async_add_executor_job(decode_latest_frames, archives)
            self._field = await self._hass.async_add_executor_job(build_field, frames)
            _LOGGER.debug(
                "Radar field rebuilt from %s frames, motion dy=%.2f dx=%.2f",
                len(frames),
                self._field.motion.dy,
                self._field.motion.dx,
            )
            return self._field

    def _is_fresh(self) -> bool:
        if self._field is None:
            return False
        age = (datetime.now(UTC) - self._field.generated_at).total_seconds()
        return age < SOURCE_CACHE_SECONDS


@dataclass(slots=True)
class LocationSettings:
    """Per-entry tuning, resolved from options with sensible defaults."""

    latitude: float
    longitude: float
    rain_threshold: float
    window_radius: int
    forecast_minutes: int

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> LocationSettings:
        options = entry.options
        return cls(
            latitude=entry.data[CONF_LATITUDE],
            longitude=entry.data[CONF_LONGITUDE],
            rain_threshold=float(
                options.get(CONF_RAIN_THRESHOLD, DEFAULT_RAIN_THRESHOLD_MM_H)
            ),
            # The options flow uses number selectors, which hand back floats. These two
            # end up in array slices and range(), so they have to be real integers.
            window_radius=int(options.get(CONF_WINDOW_RADIUS, DEFAULT_WINDOW_RADIUS_PX)),
            forecast_minutes=int(options.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)),
        )


class LocationCoordinator(DataUpdateCoordinator[LocationForecast]):
    """Keeps one configured location's forecast up to date."""

    config_entry: EstonianRadarConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EstonianRadarConfigEntry,
        source: RadarSource,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.source = source
        self.settings = LocationSettings.from_entry(entry)
        self._previous_state: str | None = None

    async def _async_update_data(self) -> LocationForecast:
        try:
            field = await self.source.async_get_field()
        except NoRadarData as err:
            raise UpdateFailed(f"No radar data available: {err}") from err
        except KaiaError as err:
            raise UpdateFailed(str(err)) from err

        forecast = await self.hass.async_add_executor_job(
            lambda: forecast_location(
                field,
                self.settings.latitude,
                self.settings.longitude,
                rain_threshold=self.settings.rain_threshold,
                window_radius=self.settings.window_radius,
                forecast_minutes=self.settings.forecast_minutes,
            )
        )

        if forecast.frame_age_minutes > MAX_FRAME_AGE_MINUTES:
            raise UpdateFailed(
                f"Latest radar frame is {forecast.frame_age_minutes:.0f} minutes old"
            )

        self._fire_transition_events(forecast)
        return forecast

    def _fire_transition_events(self, forecast: LocationForecast) -> None:
        """Emit events on state changes so automations do not have to poll."""
        state = forecast.state
        previous = self._previous_state
        self._previous_state = state

        if previous is None or state == previous:
            return

        payload = {
            "entry_id": self.config_entry.entry_id,
            "location": self.config_entry.title,
        }

        if state == "raining" and previous != "ending_soon":
            self.hass.bus.async_fire(EVENT_RAIN_STARTED, payload)
        elif state == "dry" and previous in ("raining", "ending_soon"):
            self.hass.bus.async_fire(EVENT_RAIN_STOPPED, payload)
        elif state == "starting_soon":
            self.hass.bus.async_fire(
                EVENT_RAIN_EXPECTED,
                {
                    **payload,
                    "minutes_until": forecast.rain_starts_in_minutes,
                    "severity": forecast.event.severity if forecast.event else None,
                    "total_mm": forecast.event.total_mm if forecast.event else None,
                },
            )
