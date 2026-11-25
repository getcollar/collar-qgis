# Collar for QGIS

Native [QGIS](https://qgis.org/) plugin that connects your GIS workspace to
[Collar](https://getcollar.io) — live project layers, two-way managed Tracks,
reviewed spatial edits and publishing for exploration and drilling teams.

| | |
| --- | --- |
| **QGIS** | 3.40 – 4.x (Windows, macOS, Linux) |
| **Licence** | [GPL-2.0-or-later](LICENSE) |
| **Status** | Beta (`0.4.4`) |
| **Homepage / usage** | https://getcollar.io/support/maps/collar-for-qgis |
| **Product page** | https://getcollar.io/integrations/qgis |
| **Issues** | https://github.com/getcollar/collar-qgis/issues |
| **Requires** | An active Collar organisation account |

No pip packages or separate runtime dependencies are required beyond QGIS itself.

## Install

### From a release ZIP

1. Download `collar_qgis-*.zip` from [Releases](https://github.com/getcollar/collar-qgis/releases).
2. In QGIS open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the ZIP, then enable **Collar for QGIS**.

### From source

```sh
python3 scripts/package.py
# → dist/collar_qgis-0.4.4.zip
```

Then install that ZIP in QGIS as above. Use only builds you trust.

When the plugin is accepted on [plugins.qgis.org](https://plugins.qgis.org/), install it from the Plugin Manager catalogue instead.

## Workflow

1. Open the dock from **Vector → Collar → Collar for QGIS**. Select **Connect to Collar**.
2. Sign in in your normal browser (including configured Microsoft organisation SSO).
   Confirm the connection. Unlock the QGIS authentication database when prompted.
3. Select an organisation and project. Check layers and select **Load layers**.
   Operational layers, generated layouts, rehabilitation and cloud references are read only.
   Hole attributes (depth and status) remain available in the attribute table.
4. Edit supported standalone feature layers with QGIS’s normal tools. Save the local edit
   session. Save your `.qgz` project before synchronising so connection snapshots and retry
   identities survive restarts.
5. Select **Sync changes to Collar**, review creates/updates/deletions and confirm.
   Automatic refresh defaults to every two minutes and skips editing sessions or pending changes.
   Open **Settings** to change its frequency, disable it, or choose whether to include imagery.
6. Conflicts retain the local copy and open a local-versus-Collar comparison. Review it before
   **Review conflicts / reload layer**. Reload requires confirmation and discards the active
   layer’s local edits. There is no permission-bypassing force overwrite.
7. Select a drillhole and choose **Propose hole move**. A review window stays visible while you
   click a new map position. Enter a reason and **Submit proposal**. Collar’s relocation
   workflow still requires another authorised planner to approve the move.

Multiple project groups can coexist in one QGIS workspace. Select the correct organisation
before reconnecting a saved working copy. QGIS keeps your layer renderers, labels, visibility
and tree placement when refreshing.

## Managed Tracks

Discovery exposes a single **Tracks** layer backed by Collar managed tracks:

- Load published project tracks (and your editable private drafts when you can edit).
- Style by track type (Access / Drill Access / Haul Road / Walking / Other).
- Draw or edit lines, set `type` / `stage` / `status` / `widthM`, then sync or publish.
- Creates/updates/deletes use Collar track permissions, not unmanaged spatial features.
- MultiLineString tracks are supported; simplify to at most 5,000 vertices per track.

## Publishing

Right-click a vector layer and select **Publish to Collar**, or use the dock action.
Choose the destination organisation/project in the dock first.

- **Editable mapping features** — choose a supported category. Geometry, category, name and
  notes are published; other attributes stay in the local layer.
- **Named cloud reference** — upload a vector source and keep original attributes (read only
  in this plugin after publish).
- **GeoTIFF** — stream large rasters through Collar’s existing GIS upload pipeline with
  progress and cancellation.

Supported local inputs include GeoPackage, Shapefile, GeoJSON, KML and GPX. Editable
geometries: Point, LineString, Polygon and MultiPolygon. Validate geometries before upload.
Sync is bounded (1,000 vertices per feature, 5,000 vertices / 50 changes per request,
5,000 features per publishing selection).

## Security and local data

- Browser sign-in uses a short-lived one-time code and stores the session only in QGIS’s
  encrypted authentication database.
- Credentials are sent only to `https://app.getcollar.io` over HTTPS.
- Sign out from the panel, or revoke the session under Collar **Account → Sessions**.
- Working GeoPackages live under the QGIS profile `collar/` directory and contain
  organisation spatial data. Delete them deliberately when no longer needed.
- Project files store connection identifiers and retry identities, never credentials.

## Development

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q collar_qgis
ruff check .
ruff format --check .
python3 scripts/package.py
python3 scripts/validate_package.py
```

`validate_package.py` checks the same structural rules used by plugins.qgis.org
(required metadata, `LICENSE`, package folder name, no `__pycache__` / `.pyc`, URL reachability).

Run `tests/qgis_smoke.py` with the Python interpreter bundled with your QGIS installation.
It exercises temporary working copies without a customer login. It does not replace
interactive end-to-end checks.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/PUBLISHING.md](docs/PUBLISHING.md).

## Repository layout

```
collar_qgis/     # Installable plugin package (metadata, LICENSE, README, Python modules)
scripts/         # ZIP packaging and repository validation
tests/           # Pure Python tests + QGIS smoke harness
tests/fixtures/  # Small fictional GeoJSON data for contributor checks
docs/            # Publishing checklist for maintainers
```

## Licence

Copyright (C) 2026 Collar. Distributed under the GNU General Public License v2 or later.
See [LICENSE](LICENSE).

QGIS is an independent open-source project. This plugin does not imply QGIS endorsement.
