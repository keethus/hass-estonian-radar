"""Config and options flow for the Estonian Weather Radar integration."""

from __future__ import annotations

import logging
import math
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_FORECAST_MINUTES,
    CONF_RAIN_THRESHOLD,
    CONF_WINDOW_RADIUS,
    DOMAIN,
    MAX_WINDOW_RADIUS,
    MIN_WINDOW_RADIUS,
)
from .coordinator import EstonianRadarConfigEntry, RadarSource
from .radar.const import (
    COVERAGE_OUT_OF_RANGE,
    DEFAULT_FORECAST_MINUTES,
    DEFAULT_RAIN_THRESHOLD_MM_H,
    DEFAULT_WINDOW_RADIUS_PX,
    MAX_FORECAST_MINUTES,
    MIN_FORECAST_MINUTES,
)
from .radar.geo import coverage_quality, latlon_to_pixel, nearest_radar
from .radar.kaia import KaiaError
from .radar.nowcast import sample_window

_LOGGER = logging.getLogger(__name__)


class EstonianRadarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for a name and a point on the map, then sanity-check radar coverage."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            location = user_input[CONF_LOCATION]
            latitude = location[CONF_LATITUDE]
            longitude = location[CONF_LONGITUDE]

            await self.async_set_unique_id(f"{latitude:.4f},{longitude:.4f}")
            self._abort_if_unique_id_configured()

            radar_name, distance = nearest_radar(latitude, longitude)
            coverage = coverage_quality(distance)
            description_placeholders = {
                "radar": radar_name,
                "distance": f"{distance:.0f}",
            }

            if coverage == COVERAGE_OUT_OF_RANGE:
                errors["base"] = "out_of_range"
            elif not await self._async_radar_sees(latitude, longitude):
                errors["base"] = "no_radar_data"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_LATITUDE: latitude, CONF_LONGITUDE: longitude},
                    options={},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self.hass.config.location_name
                    ): selector.TextSelector(),
                    vol.Required(
                        CONF_LOCATION,
                        default={
                            CONF_LATITUDE: self.hass.config.latitude,
                            CONF_LONGITUDE: self.hass.config.longitude,
                        },
                    ): selector.LocationSelector(),
                }
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def _async_radar_sees(self, latitude: float, longitude: float) -> bool:
        """Check a real radar frame for data at these coordinates.

        Distance to the nearest radar is a decent proxy but not the whole truth: the
        composite grid reaches further south than the radars actually paint, so a point
        can be comfortably inside the domain and still have no measurement at all. Rīga
        is exactly that case. Better to say so now than to hand someone a device whose
        every sensor reads "unknown".

        A download failure is not treated as a verdict — the location is accepted and
        the entities will report the problem themselves.
        """
        source: RadarSource = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            "source", RadarSource(self.hass)
        )
        try:
            field = await source.async_get_field()
        except (KaiaError, OSError) as err:
            _LOGGER.debug("Could not verify radar coverage now: %s", err)
            return True

        def _sample() -> float:
            y, x = latlon_to_pixel(field.latest.geometry, latitude, longitude)
            return sample_window(field.latest.data, y, x, DEFAULT_WINDOW_RADIUS_PX)

        return not math.isnan(await self.hass.async_add_executor_job(_sample))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: EstonianRadarConfigEntry,
    ) -> EstonianRadarOptionsFlow:
        return EstonianRadarOptionsFlow()


class EstonianRadarOptionsFlow(OptionsFlow):
    """Tuning knobs that do not justify re-adding the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RAIN_THRESHOLD,
                        default=options.get(CONF_RAIN_THRESHOLD, DEFAULT_RAIN_THRESHOLD_MM_H),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.01,
                            max=5.0,
                            step=0.01,
                            unit_of_measurement="mm/h",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_WINDOW_RADIUS,
                        default=options.get(CONF_WINDOW_RADIUS, DEFAULT_WINDOW_RADIUS_PX),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_WINDOW_RADIUS,
                            max=MAX_WINDOW_RADIUS,
                            step=1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_FORECAST_MINUTES,
                        default=options.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_FORECAST_MINUTES,
                            max=MAX_FORECAST_MINUTES,
                            step=5,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
        )
