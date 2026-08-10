# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-10

First release.

### Added

- Point precipitation nowcast up to 90 minutes ahead, from the Estonian Environment
  Agency's two-radar composite (KAIA open data).
- Config flow with a map picker and a radar-coverage check that refuses locations
  outside the network's range.
- Nine primary entities per location (rain state, rain rate, lead and trailing times,
  expected intensity, total, peak and duration, plus moisture and rain-expected binary
  sensors) and six diagnostics (frame time and age, nearest radar and distance, coverage
  quality, storm speed and bearing, data-problem flag).
- `estonian_radar.get_forecast` action returning the point forecast as response data.
- `estonian_radar_rain_expected`, `_rain_started` and `_rain_stopped` events.
- Options flow for rain threshold, averaging radius and forecast horizon.
- English, Latvian and Estonian translations.
- Config entry diagnostics download.

### Notes

- Storm motion is estimated with FFT phase correlation rather than an exhaustive search
  over candidate shifts. Same result, roughly 25x less CPU on a full composite grid,
  which is what makes running the whole pipeline inside Home Assistant practical.
- The forecast is never materialised as a stack of advected grids. Sampling the
  unadvected field at a back-tracked pixel gives the same answer, so adding locations
  costs almost nothing and the download and motion estimate are shared between them.
- `nodata` cells stay distinct from dry ones all the way through, so a location the
  radar cannot see reports a problem rather than reporting "dry".

[Unreleased]: https://github.com/keethus/hass-estonian-radar/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/keethus/hass-estonian-radar/releases/tag/v0.1.0
