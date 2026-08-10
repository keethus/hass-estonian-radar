"""Constants for the radar nowcast pipeline.

Values here describe the *data source* and the physics of the algorithm, not user
preferences. Anything a user may reasonably want to change lives in the integration's
options flow instead.
"""

from __future__ import annotations

from typing import Final

# --- KAIA open data endpoint -------------------------------------------------------

KAIA_ZIP_URL: Final = (
    "https://avaandmed.keskkonnaportaal.ee/_vti_bin/RmApi.svc/active/items/zipped-files"
)

#: Content type of the radar product collection in the KAIA repository.
KAIA_CONTENT_TYPE: Final = "0102FB01"

#: Phenomenon code for the multi-radar composite product.
KAIA_PHENOMENON: Final = "COMP"

#: CAP = "column maximum"-style composite product used for surface rain estimation.
KAIA_PRODUCT_MARKER: Final = ".CAP."

KAIA_PAGE_SIZE: Final = 500

# --- Frame cadence -----------------------------------------------------------------

#: The Estonian composite is published every five minutes.
FRAME_STEP_MINUTES: Final = 5

#: Number of past frames used to estimate storm motion (6 frames = 25 min of history).
PAST_FRAME_COUNT: Final = 6

#: A frame older than this is not trustworthy as "now".
MAX_FRAME_AGE_MINUTES: Final = 30

# --- Nowcast algorithm --------------------------------------------------------------

#: Reflectivity-derived rain rate (mm/h) at or above which we call it "raining".
DEFAULT_RAIN_THRESHOLD_MM_H: Final = 0.10

#: Cells below this are ignored when deciding whether a frame contains any echo at all.
MASS_THRESHOLD_MM_H: Final = 0.05

#: Half-width (in pixels) of the box averaged around the target location.
DEFAULT_WINDOW_RADIUS_PX: Final = 2

#: Largest per-frame displacement the motion search will consider, in pixels.
MAX_MOTION_SHIFT_PX: Final = 30

#: Normalised cross-correlation peak below which motion is treated as unknown.
#: Phase correlation always returns *a* peak; this guards against locking onto noise.
MIN_MOTION_CONFIDENCE: Final = 0.02

#: While it is raining, the state only reports "ending soon" if the rain stops within
#: this many minutes. Without a bound, any dry pixel inside the 90 minute horizon would
#: make ongoing rain permanently look like it was about to stop.
ENDING_SOON_MINUTES: Final = 30

DEFAULT_FORECAST_MINUTES: Final = 90
MIN_FORECAST_MINUTES: Final = 30
MAX_FORECAST_MINUTES: Final = 90

# --- Severity classification (peak rain rate, mm/h) ---------------------------------

SEVERITY_VERY_LIGHT: Final = "very_light"
SEVERITY_LIGHT: Final = "light"
SEVERITY_MODERATE: Final = "moderate"
SEVERITY_HEAVY: Final = "heavy"
SEVERITY_EXTREME: Final = "extreme"

#: Upper bound (exclusive) -> severity label. Anything above the last bound is extreme.
SEVERITY_BANDS: Final[tuple[tuple[float, str], ...]] = (
    (0.5, SEVERITY_VERY_LIGHT),
    (2.0, SEVERITY_LIGHT),
    (7.0, SEVERITY_MODERATE),
    (15.0, SEVERITY_HEAVY),
)

# --- Radar network geometry ---------------------------------------------------------

#: Estonian Environment Agency C-band Doppler radars feeding the composite.
#:
#: Coordinates are approximate (~1 km) and are used *only* to estimate how well a
#: location is covered. They never affect the nowcast itself, which reads the
#: composite grid directly.
RADAR_SITES: Final[tuple[tuple[str, float, float], ...]] = (
    ("Harku", 59.398, 24.603),
    ("Sürgavere", 58.482, 25.518),
)

#: Nominal maximum useful range of a C-band radar.
RADAR_MAX_RANGE_KM: Final = 250.0

COVERAGE_EXCELLENT: Final = "excellent"
COVERAGE_GOOD: Final = "good"
COVERAGE_MARGINAL: Final = "marginal"
COVERAGE_OUT_OF_RANGE: Final = "out_of_range"

#: Distance (km) to the nearest radar -> coverage quality. Beyond the last bound the
#: location is out of range. The bands follow beam height above ground: past ~150 km
#: the lowest beam is above 2.5 km and shallow precipitation is routinely missed.
COVERAGE_BANDS: Final[tuple[tuple[float, str], ...]] = (
    (80.0, COVERAGE_EXCELLENT),
    (150.0, COVERAGE_GOOD),
    (RADAR_MAX_RANGE_KM, COVERAGE_MARGINAL),
)
