#!/usr/bin/env python3
"""Local checks aligned with plugins.qgis.org ZIP validation rules."""

from __future__ import annotations

import configparser
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_METADATA = (
    'name',
    'description',
    'version',
    'qgisMinimumVersion',
    'author',
    'email',
    'about',
    'tracker',
    'repository',
)
PACKAGE_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9-_]+$')
NEW_PACKAGE_NAME_RE = re.compile(r'^[a-z_][a-z0-9_]*$')
FORBIDDEN_DIRS = {'__MACOSX', '.git', '__pycache__'}
MAX_BYTES = 25_000_000


def fail(message: str) -> None:
    print(f'ERROR: {message}', file=sys.stderr)
    raise SystemExit(1)


def _url_reachable(url: str) -> tuple[bool, str]:
    """Return (ok, detail). Prefer curl so macOS system trust stores are used."""
    import shutil
    import subprocess

    curl = shutil.which('curl')
    if curl:
        result = subprocess.run(
            [
                curl,
                '-fsSL',
                '-o',
                '/dev/null',
                '-w',
                '%{http_code}',
                '-A',
                'Collar-QGIS-validate/0.4.3',
                '--max-time',
                '20',
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        code = (result.stdout or '').strip()
        if result.returncode == 0 and code.isdigit() and int(code) < 400:
            return True, f'HTTP {code}'
        return (
            False,
            f'curl exit {result.returncode} HTTP {code or "n/a"} {(result.stderr or "").strip()}',
        )

    headers = {'User-Agent': 'Collar-QGIS-validate/0.4.3'}
    request = urllib.request.Request(url, method='GET', headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 400:
                return False, f'HTTP {response.status}'
            return True, f'HTTP {response.status}'
    except Exception as error:  # noqa: BLE001
        return False, str(error)


def check_urls(metadata: dict[str, str]) -> None:
    for key in ('homepage', 'tracker', 'repository'):
        url = metadata.get(key, '').strip()
        if not url:
            if key in ('tracker', 'repository'):
                fail(f'metadata {key} is required')
            continue
        ok, detail = _url_reachable(url)
        if not ok:
            fail(f'{key} URL unreachable ({detail}): {url}')
        print(f'  {key}: {detail} {url}')


def validate_zip(path: Path) -> None:
    if path.stat().st_size > MAX_BYTES:
        fail(f'ZIP exceeds 25 MB: {path}')

    with ZipFile(path) as archive:
        names = archive.namelist()
        if archive.testzip():
            fail('ZIP failed CRC check')

        for name in names:
            if '..' in name or name.startswith('/'):
                fail(f'ZIP contains unsafe path: {name}')
            if name.endswith('.pyc'):
                fail(f'ZIP contains .pyc: {name}')
            parts = name.split('/')
            for forbidden in FORBIDDEN_DIRS:
                if forbidden in parts:
                    fail(f'ZIP contains forbidden directory {forbidden}: {name}')

        package_name = names[0].split('/')[0]
        if not PACKAGE_NAME_RE.match(package_name):
            fail(f'Invalid package folder name: {package_name}')
        if not NEW_PACKAGE_NAME_RE.match(package_name):
            fail(f'New-plugin package folder must be PEP 8 snake_case: {package_name}')

        required_files = [
            f'{package_name}/__init__.py',
            f'{package_name}/metadata.txt',
            f'{package_name}/LICENSE',
        ]
        for required in required_files:
            if required not in names:
                fail(f'Missing required file in ZIP: {required}')

        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read_string(archive.read(f'{package_name}/metadata.txt').decode('utf-8'))
        if not parser.has_section('general'):
            fail('metadata.txt missing [general] section')
        metadata = dict(parser.items('general'))
        missing = [key for key in REQUIRED_METADATA if not metadata.get(key, '').strip()]
        if missing:
            fail(f'Missing required metadata fields: {", ".join(missing)}')
        if '/' in metadata['author']:
            fail('author must not contain slashes')

        icon = metadata.get('icon', '').strip()
        if icon:
            icon_path = icon[2:] if icon.startswith('./') else icon
            if f'{package_name}/{icon_path}' not in names:
                fail(f'Icon listed in metadata is missing from ZIP: {icon}')

        check_urls(metadata)
        print(f'OK {path} ({package_name} {metadata["version"]})')


def main() -> None:
    zips = sorted((ROOT / 'dist').glob('collar_qgis-*.zip'))
    if not zips:
        fail('No dist/collar_qgis-*.zip found. Run scripts/package.py first.')
    validate_zip(zips[-1])


if __name__ == '__main__':
    main()
