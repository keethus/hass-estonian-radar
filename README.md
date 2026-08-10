# Estonian Weather Radar for Home Assistant

[![HACS: custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/keethus/hass-estonian-radar?display_name=tag&sort=semver)](https://github.com/keethus/hass-estonian-radar/releases)
[![Tests](https://github.com/keethus/hass-estonian-radar/actions/workflows/tests.yml/badge.svg)](https://github.com/keethus/hass-estonian-radar/actions/workflows/tests.yml)
[![Validate](https://github.com/keethus/hass-estonian-radar/actions/workflows/validate.yml/badge.svg)](https://github.com/keethus/hass-estonian-radar/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Short-term precipitation forecasts ("nowcasts") for a specific point, derived from the
Estonian Environment Agency's multi-radar composite.

Where a normal weather integration tells you whether it will rain *today*, this one
tells you that rain will reach **your building in twelve minutes, last about half an
hour, and drop 1.8 mm** — which is the kind of thing you can actually act on.

Everything runs inside Home Assistant. There is no companion server, no MQTT bridge and
no cloud account.

## How it works

1. Every five minutes the Estonian Environment Agency publishes a radar composite
   covering Estonia and its surroundings, as ODIM_H5 files in the KAIA open data
   repository.
2. The integration downloads the last hour of frames and estimates how the
   precipitation field is moving, using FFT phase correlation over the last six frames.
3. That motion is extrapolated up to 90 minutes ahead and sampled at your coordinates.

The forecast is pure extrapolation of what the radar sees right now. It knows nothing
about convection initiating, decaying, or growing — so it is very good for the next
twenty minutes, decent for an hour, and increasingly optimistic after that.

There is a second, sharper limit near the edge of the network. Every forecast step reads
the field *upwind* of you, so the horizon is however far the radar can see in the
direction the weather is coming from. In Cēsis, with rain arriving from the south-west,
that can be fifteen minutes; with the same rain arriving from over Estonia it is the
full ninety. The `Usable forecast` diagnostic sensor reports the number honestly instead
of padding the rest of the series with a made-up "dry".

## Coverage — read this before installing

The composite comes from **two C-band radars**: Harku (near Tallinn) and Sürgavere (in
Viljandi county). Radar beams climb with distance because of their elevation angle and
the curvature of the Earth, so how much you can trust this depends almost entirely on
how far you are from the nearest one.

| Distance to nearest radar | Beam height | What you get |
|---|---|---|
| under 80 km | under 1 km | Excellent — light rain and drizzle both show |
| 80–150 km | 1–2.5 km | Good for real rain; shallow drizzle is missed |
| 150–250 km | 2.5–4 km | Only deeper systems show; expect misses |
| over 250 km | — | Out of range, refused at setup |

In practice this covers all of Estonia well, northern Latvia usefully (Cēsis sits about
130 km from Sürgavere), and Rīga marginally. Further south and west, use something else.

The radar site coordinates used for that distance are approximate to within a kilometre
or so — the agency does not publish exact ones. They only affect the reported coverage
band, never the forecast itself, which reads the composite grid directly.

Distance is only half the story. The published composite is a 720x720 grid of 1 km cells
covering roughly 21.5–28.0°E and 56.5–59.9°N, which reaches further south than the radars
actually paint — Rīga sits inside the grid and still has no measurement at all. So the
config flow does not just check the distance: it downloads a real frame and looks at your
pixel, and refuses the location if there is nothing there.

The integration reports its own coverage rather than hiding it: every location gets a
`Radar coverage` sensor, and a `Radar data problem` binary sensor that turns on when the
radar cannot see your location at all. A location the radar cannot see must never read
as "dry" — that is the difference between *we looked and it is not raining* and *we did
not look*.

## Installation

### HACS

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=keethus&repository=hass-estonian-radar&category=integration)

Or by hand:

1. HACS → three-dot menu → **Custom repositories**
2. Add `https://github.com/keethus/hass-estonian-radar`, category **Integration**
3. Install **Estonian Weather Radar**, then restart Home Assistant
4. Add the integration:

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=estonian_radar)

### Manual

Copy `custom_components/estonian_radar` into your `config/custom_components/` directory
and restart. Home Assistant 2025.2 or newer is required.

First start pulls `h5py` and `pyproj` (about 30 MB of wheels, once). Both publish
musllinux wheels, so Home Assistant OS and Container installs on amd64 and aarch64 work
out of the box. 32-bit ARM has no wheels for these and is not supported.

## Configuration

Add one entry per location — the entry name becomes the device name, so entities come
out as `sensor.<your_name>_rain`. Multiple locations in one Home Assistant share a
single download and a single motion calculation.

Options (Settings → Devices & Services → Estonian Weather Radar → Configure):

| Option | Default | What it does |
|---|---|---|
| Rain threshold | 0.10 mm/h | Rate at or above which the location counts as wet |
| Averaging radius | 2 px | Radar pixels averaged around the point; larger is smoother, less local |
| Forecast horizon | 90 min | How far ahead to extrapolate |

## Entities

Per location:

| Entity | Description |
|---|---|
| `sensor.<name>_rain` | `dry` / `raining` / `starting_soon` / `ending_soon` — the one to put on a dashboard |
| `sensor.<name>_rain_rate` | Current rate in mm/h; carries the full point forecast as an attribute |
| `sensor.<name>_rain_starts_in` | Minutes until rain arrives |
| `sensor.<name>_rain_ends_in` | Minutes until it stops |
| `sensor.<name>_expected_intensity` | `very_light` … `extreme` |
| `sensor.<name>_expected_total` | Millimetres expected from the coming event |
| `sensor.<name>_expected_peak` | Peak rate expected, mm/h |
| `sensor.<name>_expected_duration` | How long the event should last |
| `binary_sensor.<name>_raining` | Moisture |
| `binary_sensor.<name>_rain_expected` | Rain within the forecast horizon |
| `binary_sensor.<name>_radar_data_problem` | Problem — stale frames or no coverage |

Diagnostics (some disabled by default): `usable_forecast` (how far ahead the radar can
actually see from here right now), latest radar frame time, frame age, nearest radar and
distance, coverage quality, storm speed and bearing.

### Events

| Event | Fired when | Data |
|---|---|---|
| `estonian_radar_rain_expected` | Rain appears in the forecast | `minutes_until`, `severity`, `total_mm` |
| `estonian_radar_rain_started` | Rain reaches the location | |
| `estonian_radar_rain_stopped` | Rain clears | |

### Action

`estonian_radar.get_forecast` returns the point forecast as response data:

```yaml
action: estonian_radar.get_forecast
target:
  entity_id: sensor.home_rain_rate
response_variable: nowcast
```

```json
{
  "location": "Home",
  "frame_time": "2026-08-10T09:15:00+00:00",
  "step_minutes": 5,
  "coverage_quality": "good",
  "forecast": [
    { "datetime": "2026-08-10T09:20:00+00:00", "precipitation": 0.0 },
    { "datetime": "2026-08-10T09:25:00+00:00", "precipitation": 0.4 },
    { "datetime": "2026-08-10T09:30:00+00:00", "precipitation": 2.1 },
    { "datetime": "2026-08-10T09:35:00+00:00", "precipitation": null }
  ]
}
```

A `null` is not zero. It means the radar has nothing to say about that step, because the
sample point for it lies outside the area the network covers.

## Language

Entity names and states are translated by Home Assistant per user, so a Latvian and an
English user looking at the same dashboard each see their own language. English,
Latvian and Estonian ship with the integration.

Because of that, the integration deliberately does **not** produce ready-made sentences
— those would be stuck in one language and one grammatical case. Build them in your
dashboard instead:

```yaml
type: markdown
content: >-
  {% set mins = states('sensor.home_rain_starts_in') %}
  {% if mins not in ['unknown', 'unavailable'] %}
    Rain in about {{ mins }} min
    ({{ states('sensor.home_expected_intensity') }},
    {{ states('sensor.home_expected_total') }} mm)
  {% else %}
    No rain expected in the next 90 minutes
  {% endif %}
```

## Recorder

The 18-value point forecast and the motion-confidence attribute are marked as
unrecorded, so they never reach the database while remaining available to templates and
charts. Everything else is small enough that no exclusions are needed.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest
```

The `custom_components/estonian_radar/radar/` package contains the whole nowcast
pipeline and imports nothing from Home Assistant, so it can be tested — and reused — on
its own.

## Credits

Radar data © [Estonian Environment Agency
(Keskkonnaagentuur)](https://keskkonnaportaal.ee), published as open data via the KAIA
repository. The Estonian Environment Agency's terms allow reuse of this data; this
project is not affiliated with or endorsed by them.

Motion estimation follows the standard optical-flow-by-phase-correlation approach used
in radar nowcasting.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The nowcast pipeline has no Home Assistant
imports, so `pytest` runs in under a second without a Home Assistant install.

## Licence

MIT
