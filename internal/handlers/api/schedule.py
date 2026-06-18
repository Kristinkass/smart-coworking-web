"""Coworking schedule API."""
from datetime import datetime

from flask import jsonify, request

from internal.handlers.deps import Coworking, CoworkingSchedule, admin_required, db
from internal.models.schedule import parse_schedule_time


def _coworking_id():
    cw = Coworking.get_singleton()
    return cw.id if cw else 1


def register_schedule_routes(app):
    @app.route('/api/admin/schedule', methods=['GET'])
    @admin_required
    def get_schedule():
        """Получить расписание коворкинга по дням недели"""
        try:
            cw_id = _coworking_id()
            schedules = CoworkingSchedule.query.filter_by(
                id_coworking=cw_id,
            ).order_by(CoworkingSchedule.day_of_week).all()
            if not schedules:
                CoworkingSchedule.init_default_schedule(cw_id)
                schedules = CoworkingSchedule.query.filter_by(
                    id_coworking=cw_id,
                ).order_by(CoworkingSchedule.day_of_week).all()
            return jsonify({'success': True, 'schedule': [s.to_dict() for s in schedules]})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/admin/schedule/<int:schedule_id>', methods=['PUT'])
    @admin_required
    def update_schedule(schedule_id):
        """Обновить расписание для конкретного дня."""
        try:
            data = request.get_json()
            schedule = CoworkingSchedule.query.get_or_404(schedule_id)
            if schedule.id_coworking != _coworking_id():
                return jsonify({'success': False, 'error': 'Расписание не принадлежит текущему коворкингу'}), 404
            if 'open_time' in data:
                schedule.open_time = parse_schedule_time(data['open_time'])
            if 'close_time' in data:
                schedule.close_time = parse_schedule_time(
                    data['close_time'], as_close=True, open_time=schedule.open_time,
                )
            if 'is_active' in data:
                schedule.is_active = data['is_active']
            if 'is_bookable' in data:
                schedule.is_bookable = data['is_bookable']
            db.session.commit()
            return jsonify({'success': True, 'schedule': schedule.to_dict()})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/admin/schedule/apply-to-all', methods=['POST'])
    @admin_required
    def apply_schedule_to_all():
        """Применить расписание одного дня ко всем дням недели."""
        try:
            data = request.get_json()
            source_day = data.get('source_day', 0)
            target_days = data.get('target_days', [0, 1, 2, 3, 4])
            cw_id = _coworking_id()

            source = CoworkingSchedule.query.filter_by(
                id_coworking=cw_id,
                day_of_week=source_day,
            ).first()
            if not source:
                return jsonify({'success': False, 'error': 'Исходный день не найден'}), 404

            for day in target_days:
                target = CoworkingSchedule.query.filter_by(
                    id_coworking=cw_id,
                    day_of_week=day,
                ).first()
                if not target:
                    target = CoworkingSchedule(id_coworking=cw_id, day_of_week=day)
                    db.session.add(target)
                target.open_time = source.open_time
                target.close_time = source.close_time
                target.is_active = source.is_active
                target.is_bookable = source.is_bookable

            db.session.commit()
            return jsonify({'success': True, 'message': f'Расписание применено к {len(target_days)} дням'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/admin/schedule/reset', methods=['POST'])
    @admin_required
    def reset_schedule():
        """Сбросить расписание к значениям по умолчанию."""
        try:
            cw_id = _coworking_id()
            CoworkingSchedule.query.filter_by(id_coworking=cw_id).delete()
            db.session.commit()
            CoworkingSchedule.init_default_schedule(cw_id)
            return jsonify({'success': True, 'message': 'Расписание сброшено к значениям по умолчанию'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
