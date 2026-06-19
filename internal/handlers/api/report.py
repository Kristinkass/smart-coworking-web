"""Reports and PDF export."""
from datetime import datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape

from flask import jsonify, request, send_file
from sqlalchemy.orm import joinedload

from internal.handlers.deps import admin_required, models
from internal.utils.errors import user_error_message
from internal.utils.formatters import (
    REPORT_SECTIONS,
    build_report_stats,
    format_booking_duration_display,
    format_booking_subscription_name,
    format_booking_time_or_period,
    format_place_code,
    format_place_container,
    get_status_name,
)
from internal.utils.pdf_fonts import register_pdf_fonts


def _pdf_escape(text):
    return escape(str(text or '-'))


def _pdf_cell(text, style):
    from reportlab.platypus import Paragraph
    return Paragraph(_pdf_escape(text), style)


def _formal_table_style(font_name, bold_name, header_rows=1):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('FONTNAME', (0, 0), (-1, header_rows - 1), bold_name),
        ('FONTNAME', (0, header_rows), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('LINEBELOW', (0, header_rows - 1), (-1, header_rows - 1), 1, colors.black),
        ('WORDWRAP', (0, 0), (-1, -1), True),
    ])


def _build_section_table(section_key, section_mode, value_header, bookings, cell_style, header_style, font_name, bold_name):
    from reportlab.platypus import Paragraph, Spacer, Table

    if not bookings:
        return []

    title = next(s['title'] for s in REPORT_SECTIONS if s['key'] == section_key)
    elements = [
        Spacer(1, 10),
        Paragraph(_pdf_escape(f'{title} ({len(bookings)})'), header_style),
        Spacer(1, 4),
    ]

    time_header = 'Период' if section_mode == 'period' else 'Время'
    headers = ['№', 'Дата', time_header, 'Пользователь', 'Место', 'Локация']
    if section_mode == 'subscription':
        headers.append('Абонемент')
    elif value_header:
        headers.append(value_header)
    headers.extend(['Сумма', 'Статус'])
    table_data = [[Paragraph(_pdf_escape(h), cell_style) for h in headers]]

    for idx, booking in enumerate(bookings, start=1):
        place_code = format_place_code(booking.place) if booking.place else '-'
        if booking.place and booking.place.name:
            place_code = f'{booking.place.name} ({place_code})'
        location_label = format_place_container(booking.place) if booking.place else ''
        row = [
            _pdf_cell(str(idx), cell_style),
            _pdf_cell(booking.booking_date.strftime('%d.%m.%Y'), cell_style),
            _pdf_cell(format_booking_time_or_period(booking), cell_style),
            _pdf_cell(booking.user.username if booking.user else '-', cell_style),
            _pdf_cell(place_code, cell_style),
            _pdf_cell(location_label or '-', cell_style),
        ]
        if section_mode == 'subscription':
            row.append(_pdf_cell(format_booking_subscription_name(booking), cell_style))
        elif value_header:
            row.append(_pdf_cell(format_booking_duration_display(booking), cell_style))
        row.extend([
            _pdf_cell(f"{int(round(booking.total_price or 0))} ₽", cell_style),
            _pdf_cell(get_status_name(booking.status), cell_style),
        ])
        table_data.append(row)

    col_count = len(headers)
    page_width = 523
    weights = {
        '№': 0.5,
        'Дата': 0.9,
        'Время': 1.0,
        'Период': 1.2,
        'Пользователь': 1.1,
        'Место': 1.4,
        'Локация': 1.2,
        'Абонемент': 1.1,
        'Длительность': 0.9,
        'Сумма': 0.8,
        'Статус': 0.9,
    }
    total_w = sum(weights.get(h, 1.0) for h in headers)
    col_widths = [page_width * weights.get(h, 1.0) / total_w for h in headers]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(_formal_table_style(font_name, bold_name))
    elements.append(table)
    return elements


def register_report_routes(app):
    @app.route('/api/admin/reports/pdf')
    @admin_required
    def generate_pdf_report():
        """Генерация PDF отчета"""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            report_type = request.args.get('type', 'all')

            if not start_date_str:
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=30)
            else:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            query = models.Booking.query.filter(
                models.Booking.booking_date >= start_date,
                models.Booking.booking_date <= end_date,
            )
            if report_type == 'completed':
                query = query.filter_by(status='completed')
            elif report_type == 'active':
                query = query.filter_by(status='active')
            elif report_type == 'cancelled':
                query = query.filter_by(status='cancelled')

            bookings = query.options(
                joinedload(models.Booking.user),
                joinedload(models.Booking.place),
                joinedload(models.Booking.subscription),
            ).order_by(models.Booking.booking_date.desc()).all()

            stats, grouped = build_report_stats(bookings)

            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                leftMargin=36,
                rightMargin=36,
                topMargin=36,
                bottomMargin=36,
            )
            elements = []

            font_name, bold_name = register_pdf_fonts(pdfmetrics, TTFont)

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'ReportTitle',
                parent=styles['Title'],
                fontName=bold_name,
                fontSize=14,
                leading=16,
                textColor='black',
            )
            normal_style = ParagraphStyle(
                'ReportNormal',
                parent=styles['Normal'],
                fontName=font_name,
                fontSize=9,
                leading=11,
                textColor='black',
            )
            cell_style = ParagraphStyle(
                'Cell',
                parent=normal_style,
                fontSize=7,
                leading=9,
                wordWrap='CJK',
            )
            section_style = ParagraphStyle(
                'Section',
                parent=normal_style,
                fontName=bold_name,
                fontSize=10,
                spaceAfter=2,
            )

            type_labels = {
                'all': 'Все бронирования',
                'completed': 'Завершённые бронирования',
                'active': 'Активные бронирования',
                'cancelled': 'Отменённые бронирования',
            }
            elements.append(Paragraph('Отчёт по бронированиям коворкинга', title_style))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(
                f"Тип: {type_labels.get(report_type, report_type)} · "
                f"Период: {start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}",
                normal_style,
            ))
            elements.append(Spacer(1, 10))

            page_width = 523
            stats_rows = [
                [_pdf_cell('Показатель', cell_style), _pdf_cell('Значение', cell_style)],
                [_pdf_cell('Всего бронирований', cell_style), _pdf_cell(str(stats['total_bookings']), cell_style)],
                [_pdf_cell('Общий доход', cell_style), _pdf_cell(f"{stats['total_revenue']:.2f} ₽", cell_style)],
                [_pdf_cell('Уникальных пользователей', cell_style), _pdf_cell(str(stats['unique_users']), cell_style)],
            ]
            for row in stats.get('tariff_summary', []):
                stats_rows.append([
                    _pdf_cell(row['label'], cell_style),
                    _pdf_cell(row['detail'], cell_style),
                ])
            for row in stats.get('subscription_summary', []):
                stats_rows.append([
                    _pdf_cell(f"Абонемент: {row['label']}", cell_style),
                    _pdf_cell(row['detail'], cell_style),
                ])

            stats_table = Table(stats_rows, colWidths=[page_width * 0.55, page_width * 0.45])
            stats_table.setStyle(_formal_table_style(font_name, bold_name))
            elements.append(stats_table)

            for section in REPORT_SECTIONS:
                elements.extend(
                    _build_section_table(
                        section['key'], section['mode'], section['value_label'],
                        grouped[section['key']],
                        cell_style, section_style, font_name, bold_name,
                    )
                )

            doc.build(elements)
            buffer.seek(0)
            return send_file(
                buffer,
                as_attachment=True,
                download_name=f'report_{start_date}_{end_date}.pdf',
                mimetype='application/pdf',
            )

        except Exception as e:
            print(f'Ошибка генерации PDF: {e}')
            import traceback
            traceback.print_exc()
            return jsonify({'error': user_error_message(e)}), 500
