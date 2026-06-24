"""Скачать DejaVu для PDF с кириллицей (без apt в Docker)."""
from __future__ import annotations

import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / 'assets' / 'fonts'
FILES = ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')
BASE_URL = 'https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/'


def ensure_pdf_fonts() -> bool:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for name in FILES:
        dest = FONT_DIR / name
        if dest.is_file() and dest.stat().st_size > 1000:
            continue
        try:
            req = urllib.request.Request(
                BASE_URL + name,
                headers={'User-Agent': 'smart-coworking/1.0'},
            )
            with urllib.request.urlopen(req, timeout=8) as resp, open(dest, 'wb') as out:
                out.write(resp.read())
            print(f'[fonts] {name}')
        except OSError as exc:
            print(f'[fonts] warning: {name}: {exc}')
            ok = False
    return ok


if __name__ == '__main__':
    raise SystemExit(0 if ensure_pdf_fonts() else 1)
