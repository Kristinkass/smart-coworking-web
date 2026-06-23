"""Тесты нормализации кодов мест."""

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'layout_codes',
    _ROOT / 'internal' / 'layout' / 'codes.py',
)
codes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(codes)


class TestCodeNormalize:
    def test_cyrillic_pc_to_latin(self):
        assert codes.normalize_code_chars('1РС-T26') == '1PC-T26'

    def test_codes_match_homoglyphs(self):
        assert codes.codes_match('1РС-T26', '1PC-T26')
        assert not codes.codes_match('1A-T1', '1B-T1')

    def test_find_layout_place(self):
        places = [
            {'code': '1РС-T26', 'kind': 'desk', 'location': '1РС'},
            {'code': '1A-L1', 'kind': 'space', 'location': '1A'},
        ]
        found, canonical = codes.find_layout_place('1PC-T26', places)
        assert found is not None
        assert canonical == '1РС-T26'
