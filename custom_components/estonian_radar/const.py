"""Constants for the Estonian Weather Radar integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "estonian_radar"

MANUFACTURER: Final = "Estonian Environment Agency"
MODEL: Final = "KAIA radar composite nowcast"
CONFIGURATION_URL: Final = (
    "https://keskkonnaportaal.ee/en/topics/remote-sensing/weather-radars"
)
ATTRIBUTION: Final = "Data provided by the Estonian Environment Agency (Keskkonnaagentuur)"

#: The composite is published every five minutes; polling faster only wastes requests.
UPDATE_INTERVAL: Final = timedelta(minutes=5)

#: How long a downloaded and decoded radar field stays usable before a refetch.
SOURCE_CACHE_SECONDS: Final = 240

# --- Options ------------------------------------------------------------------------

CONF_RAIN_THRESHOLD: Final = "rain_threshold"
CONF_WINDOW_RADIUS: Final = "window_radius"
CONF_FORECAST_MINUTES: Final = "forecast_minutes"

MIN_WINDOW_RADIUS: Final = 0
MAX_WINDOW_RADIUS: Final = 10

# --- Events --------------------------------------------------------------------------

EVENT_RAIN_EXPECTED: Final = f"{DOMAIN}_rain_expected"
EVENT_RAIN_STARTED: Final = f"{DOMAIN}_rain_started"
EVENT_RAIN_STOPPED: Final = f"{DOMAIN}_rain_stopped"

# --- Services -------------------------------------------------------------------------

SERVICE_GET_FORECAST: Final = "get_forecast"

# --- States ---------------------------------------------------------------------------

STATE_DRY: Final = "dry"
STATE_RAINING: Final = "raining"
STATE_STARTING_SOON: Final = "starting_soon"
STATE_ENDING_SOON: Final = "ending_soon"

RAIN_STATES: Final = [STATE_DRY, STATE_RAINING, STATE_STARTING_SOON, STATE_ENDING_SOON]

SEVERITY_STATES: Final = [
    "very_light",
    "light",
    "moderate",
    "heavy",
    "extreme",
]

COVERAGE_STATES: Final = ["excellent", "good", "marginal", "out_of_range"]
