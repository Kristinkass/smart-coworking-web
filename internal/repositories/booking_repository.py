"""Booking data access."""
from internal.models import Booking, db


class BookingRepository:
    @staticmethod
    def get_by_id(booking_id):
        return db.session.get(Booking, booking_id)

    @staticmethod
    def get_or_404(booking_id):
        return Booking.query.get_or_404(booking_id)

    @staticmethod
    def get_active_for_place_on_date(place_id, booking_date):
        return Booking.query.filter(
            Booking.place_id == place_id,
            Booking.booking_date == booking_date,
            Booking.status == 'active',
        ).order_by(Booking.start_time).all()

    @staticmethod
    def save(booking):
        db.session.add(booking)
        db.session.commit()
        return booking
