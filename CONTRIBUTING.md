# Contributing

## Running the tests

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

The tests cover `custom_components/estonian_radar/radar/`, which is the whole nowcast
pipeline and imports nothing from Home Assistant. That is deliberate: the interesting
logic can be exercised in a fraction of a second without a Home Assistant install, and
the Home Assistant layer above it stays thin enough to read.

## Layout

| Path | What lives there |
|---|---|
| `radar/kaia.py` | Talking to the KAIA open data repository |
| `radar/odim.py` | Turning ODIM_H5 files into rain-rate grids |
| `radar/geo.py` | Projection, distances, coverage classification |
| `radar/nowcast.py` | Motion estimation and point forecasting |
| `coordinator.py` | The shared radar source and the per-location coordinators |
| `sensor.py`, `binary_sensor.py` | Entity definitions |

## Things worth knowing before changing the algorithm

- `NaN` means the radar has no measurement there. It must never be collapsed to zero,
  because "we did not look" and "it is not raining" are different answers.
- Motion is the median of the per-frame-pair estimates, not the mean, so one bad scan
  cannot drag the forecast off course.
- Lead times are anchored to the radar frame, which is already a few minutes old when it
  is published. Frame age is subtracted before anything is reported to the user.

## Releasing

Bump `version` in `custom_components/estonian_radar/manifest.json`, add a `CHANGELOG.md`
entry, then push a matching `vX.Y.Z` tag. The release workflow refuses tags that do not
match the manifest.
