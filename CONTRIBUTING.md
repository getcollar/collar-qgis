# Contributing

Thank you for helping improve Collar for QGIS.

## Development setup

1. Install [QGIS](https://qgis.org/) 3.40 or later (4.x is supported).
2. Clone this repository.
3. Package a local ZIP and install it, or symlink the `collar_qgis` folder into your QGIS profile `python/plugins/` directory.
4. Restart QGIS and enable **Collar for QGIS**.

```sh
python3 scripts/package.py
```

Then in QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.

## Tests

Pure Python unit tests (no QGIS runtime required):

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q collar_qgis
ruff check .
ruff format --check .
```

For a small, fictional manual-test layer, load
`tests/fixtures/outback_minerals_minimal.geojson` into a scratch QGIS project.

Headless smoke checks that need the QGIS Python environment:

```sh
# Paths vary by OS / install. See README → Development.
python3 tests/qgis_smoke.py
```

## Pull requests

- Keep customer spatial data and session secrets out of logs, screenshots and fixtures.
- Prefer additive changes that stay compatible with the live Collar `/api/v1/qgis` contract.
- Update `CHANGELOG.md` and the `changelog` field in `metadata.txt` for user-visible changes.
- Bump `version` in `metadata.txt` when you intend to release.

## Licence

Contributions are accepted under the GNU General Public License v2 or later. See `LICENSE`.
