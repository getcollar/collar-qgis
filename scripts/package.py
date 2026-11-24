#!/usr/bin/env python3
"""Build an installable plugin ZIP for QGIS (Install from ZIP or plugins.qgis.org)."""

from __future__ import annotations

import configparser
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'collar_qgis'
INCLUDED_SUFFIXES = {'.py', '.txt', '.svg', '.png', '.md', '.html', '.qml', '.json'}
# Extensionless files that must ship inside the plugin folder.
INCLUDED_NAMES = {'LICENSE', 'COPYING', 'AUTHORS', 'CHANGELOG'}


def should_include(path: Path) -> bool:
    if not path.is_file():
        return False
    if '__pycache__' in path.parts or path.name.startswith('.'):
        return False
    if path.name in INCLUDED_NAMES:
        return True
    return path.suffix.lower() in INCLUDED_SUFFIXES


def main() -> Path:
    metadata = configparser.ConfigParser()
    metadata.optionxform = str
    metadata.read(PLUGIN / 'metadata.txt', encoding='utf-8')
    version = metadata['general']['version']
    output = ROOT / 'dist' / f'collar_qgis-{version}.zip'
    output.parent.mkdir(exist_ok=True)

    required = [PLUGIN / 'metadata.txt', PLUGIN / '__init__.py', PLUGIN / 'LICENSE']
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f'Missing required plugin files: {", ".join(missing)}')

    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(PLUGIN.rglob('*')):
            if should_include(path):
                archive.write(path, path.relative_to(ROOT).as_posix())

    print(output)
    return output


if __name__ == '__main__':
    main()
