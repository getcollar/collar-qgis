# Publishing to the QGIS Plugin Repository

Checklist aligned with https://plugins.qgis.org/docs/publish and
https://plugins.qgis.org/docs/approval.

## Repository requirements (already prepared in this repo)

- [x] Public source at https://github.com/getcollar/collar-qgis (not a ZIP)
- [x] Issue tracker at https://github.com/getcollar/collar-qgis/issues
- [x] Usage homepage at https://getcollar.io/support/maps/collar-for-qgis
- [x] English `description` and detailed `about` in `collar_qgis/metadata.txt`
- [x] GPL-2.0-or-later `LICENSE` file **without extension** inside `collar_qgis/`
- [x] Plugin README inside the package folder
- [x] PNG icon referenced by `icon=icon.png`
- [x] `changelog` field populated
- [x] Account requirement and “no pip deps” stated in `about`
- [x] `experimental=True` (QGIS Plugin Manager flag) while product status remains beta; clear only for a deliberate stable release
- [x] Package folder name `collar_qgis` (ASCII snake_case, PEP 8)

## Package and validate

```sh
python3 scripts/package.py
python3 scripts/validate_package.py
# → dist/collar_qgis-<version>.zip
```

The ZIP must contain a single top-level folder `collar_qgis/` with at least:

- `metadata.txt`
- `__init__.py`
- `LICENSE`
- no `.pyc`, `__pycache__`, `.git` or `__MACOSX`
- size under 25 MB, no binaries

## Acceptance gates before first upload

Do not upload until these pass:

- [x] Interactive browser sign-in, including Microsoft organisation SSO where configured
- [x] Authorised sync, conflict and publishing scenarios with concurrent clients
- [x] QGIS 3.40 and 4.x on Windows, macOS and Linux
- [x] Upload interruption, cancellation and replacement against the live service
- [x] User-facing Plugin Manager screenshots / layout checks
- [x] Pure Python tests and `tests/qgis_smoke.py` against a real QGIS install
- [x] Uploaded ZIP contents match the tagged commit in this repository

## Upload

1. Obtain an [OSGeo ID](https://www.osgeo.org/community/getting-started-osgeo/osgeo-userid/).
2. Tag the release (`v0.4.3`) and attach `dist/collar_qgis-0.4.3.zip` to the GitHub Release.
3. Sign in at https://plugins.qgis.org/ and upload the same ZIP.
4. Wait for staff approval. New plugins are reviewed before they appear publicly.
5. After approval, update Collar marketing/support copy so it no longer says the
   plugin is unavailable from the official repository.

## After each update

- Bump `version` (must be unique per upload)
- Refresh `changelog` in `metadata.txt` and `CHANGELOG.md`
- Re-run `scripts/validate_package.py` so homepage / repository / tracker still resolve
- Keep `experimental=True` (QGIS flag) until the team marks a stable release; product copy should say Beta, not Experimental

## Support copy

- https://getcollar.io/support/maps/collar-for-qgis
- https://getcollar.io/support/maps/qgis-sync-and-publish
