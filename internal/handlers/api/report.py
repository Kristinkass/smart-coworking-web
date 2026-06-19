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


def _pdf_escape(text):
    return escape(str(text or '-'))


def _pdf_cell(text, style):
    from reportlab.platypus import Paragraph
    return Paragraph(_pdf_escape(text), style)


def _build_section_table(section_key, section_mode, value_header, bookings, cell_style, header_style, font_name):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    if not bookings:
        return []

    title = next(s['title'] for s in REPORT_SECTIONS if s['key'] == section_key)
    elements = [
        Spacer(1, 12),
        Paragraph(_pdf_escape(title), header_style),
        Spacer(1, 6),
    ]

    time_header = 'Период' if section_mode == 'period' else 'Время'
    headers = ['Дата', time_header, 'Пользователь', 'Место', 'Локация']
    if section_mode == 'subscription':
        headers.append('Абонемент')
    headers.extend([value_header, 'Сумма', 'Статус'])
    table_data = [[Paragraph(_pdf_escape(h), cell_style) for h in headers]]

    for booking in bookings:
        place_code = format_place_code(booking.place) if booking.place else '-'
        if booking.place and booking.place.name:
            place_code = f'{booking.place.name} ({place_code})'
        location_label = format_place_container(booking.place) if booking.place else ''
        row = [
            _pdf_cell(booking.booking_date.strftime('%d.%m.%Y'), cell_style),
            _pdf_cell(format_booking_time_or_period(booking), cell_style),
            _pdf_cell(booking.user.username if booking.user else '-', cell_style),
            _pdf_cell(place_code, cell_style),
            _pdf_cell(location_label or '-', cell_style),
        ]
        if section_mode == 'subscription':
            row.append(_pdf_cell(format_booking_subscription_name(booking), cell_style))
        row.extend([
            _pdf_cell(format_booking_duration_display(booking), cell_style),
            _pdf_cell(f"{int(round(booking.total_price or 0))} ₽", cell_style),
            _pdf_cell(get_status_name(booking.status), cell_style),
        ])
        table_data.append(row)

    col_count = len(headers)
    page_width = 523  # A4 минус поля 36pt с каждой стороны
    col_width = page_width / col_count
    col_widths = [col_width] * col_count

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, 0), font_name + '-Bold' if font_name == 'Arial' else 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('WORDWRAP', (0, 0), (-1, -1), True),
    ]))
    elements.append(table)
    return elements


def register_report_routes(app):
    @app.route('/api/admin/reports/pdf')
    @admin_required
    def generate_pdf_report():
        """Генерация PDF отчета"""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
            import os

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

            font_path = 'C:\\Windows\\Fonts\\arial.ttf'
            font_name = 'Arial'
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('Arial', font_path))
                pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:\\Windows\\Fonts\\arialbd.ttf'))
            else:
                font_name = 'Helvetica'

            styles = getSampleStyleSheet()
            if font_name == 'Arial':
                for name in ('Title', 'Normal', 'Heading2'):
                    styles[name].fontName = 'Arial-Bold' if name != 'Normal' else 'Arial'

            cell_style = ParagraphStyle(
                'Cell',
                parent=styles['Normal'],
                fontName=font_name,
                fontSize=8,
                leading=10,
                wordWrap='CJK',
            )
            section_style = ParagraphStyle(
                'Section',
                parent=styles['Heading2'],
                fontName='Arial-Bold' if font_name == 'Arial' else 'Helvetica-Bold',
                fontSize=11,
                spaceAfter=4,
            )

            elements.append(Paragraph('Отчет по бронированиям коворкинга', styles['Title']))
            elements.append(Spacer(1, 8))
            elements.append(Paragraph(
                f"Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}",
                styles['Normal'],
            ))
            elements.append(Spacer(1, 12))

            page_width = 523  # A4 минус поля 36pt с каждой стороны
            stats_rows = [
                ['Показатель', 'Значение'],
                ['Всего бронирований', str(stats['total_bookings'])],
                ['Общий доход', f"{stats['total_revenue']:.2f} ₽"],
            ]
            for row in stats.get('tariff_summary', []):
                stats_rows.append([row['label'], row['detail']])
            for row in stats.get('subscription_summary', []):
                stats_rows.append([f"Абонемент: {row['label']}", row['detail']])

            stats_table = Table(stats_rows, colWidths=[page_width / 2, page_width / 2])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), font_name + '-Bold' if font_name == 'Arial' else 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('WORDWRAP', (0, 0), (-1, -1), True),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ]))
            elements.append(stats_table)

            for section in REPORT_SECTIONS:
                elements.extend(
                    _build_section_table(
                        section['key'], section['mode'], section['value_label'],
                        grouped[section['key']],
                        cell_style, section_style, font_name,
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
