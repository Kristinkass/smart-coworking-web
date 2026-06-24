"""Регистрация шрифтов с поддержкой кириллицы для ReportLab PDF."""
import os

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_BUNDLED_FONTS = os.path.join(_PROJECT_ROOT, 'assets', 'fonts')


def register_pdf_fonts(pdfmetrics, TTFont):
    """Зарегистрировать TTF-шрифт. Возвращает (regular_name, bold_name)."""
    candidates = [
        (
            'ReportFont',
            os.path.join(_BUNDLED_FONTS, 'DejaVuSans.ttf'),
            os.path.join(_BUNDLED_FONTS, 'DejaVuSans-Bold.ttf'),
        ),
        (
            'ReportFont',
            r'C:\Windows\Fonts\arial.ttf',
            r'C:\Windows\Fonts\arialbd.ttf',
        ),
        (
            'ReportFont',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        ),
        (
            'ReportFont',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        ),
    ]

    for name, regular_path, bold_path in candidates:
        if not os.path.isfile(regular_path):
            continue
        pdfmetrics.registerFont(TTFont(name, regular_path))
        bold_name = f'{name}-Bold'
        if os.path.isfile(bold_path):
            pdfmetrics.registerFont(TTFont(bold_name, bold_path))
        else:
            bold_name = name
        return name, bold_name

    return 'Helvetica', 'Helvetica-Bold'
