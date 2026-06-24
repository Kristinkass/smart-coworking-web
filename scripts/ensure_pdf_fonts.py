"""Скачать DejaVu для PDF с кириллицей (без apt в Docker)."""
from __future__ import annotations

import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / 'assets' / 'fonts'
FILES = ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')
BASE_URL = 'https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/version_2_37/ttf/'


def ensure_pdf_fonts() -> bool:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for name in FILES:
        dest = FONT_DIR / name
        if dest.is_file() and dest.stat().st_size > 1000:
            continue
        try:
            urllib.request.urlretrieve(BASE_URL + name, dest)
            print(f'[fonts] {name}')
        except OSError as exc:
            print(f'[fonts] warning: {name}: {exc}')
            ok = False
    return ok


if __name__ == '__main__':
    raise SystemExit(0 if ensure_pdf_fonts() else 1)
