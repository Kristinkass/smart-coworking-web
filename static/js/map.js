// Логика для страницы с картой

const places = {{ places|safe }};

const map = document.getElementById('map');

places.forEach(place => {
    const el = document.createElement('div');
    el.classList.add('place');
    el.classList.add(place.status);

    if (place.type === 'room') el.classList.add('room');
    if (place.type === 'office') el.classList.add('office');

    el.style.gridColumn = place.x;
    el.style.gridRow = place.y;
    el.style.gridColumnEnd = "span " + place.width;
    el.style.gridRowEnd = "span " + place.height;

    el.innerText = place.name;

    el.onclick = () => {
        if (typeof showToast === 'function') showToast(`Место: ${place.name}\nЦена: ${place.price_per_hour}`, 'info');
    };

    map.appendChild(el);
});

class MapManager {
    constructor() {
        this.places = window.placesData || [];
        this.selectedPlace = null;
        this.userBookings = [];
        this.init();
    }

    init() {
        this.renderMap();
        this.setupEventListeners();
        this.loadUserBookings();
    }

    renderMap() {
        const mapGrid = document.getElementById('map-grid');
        if (!mapGrid) return;

        mapGrid.innerHTML = '';

        // Сортируем места по координатам для лучшего отображения
        this.places.sort((a, b) => {
            if (a.y === b.y) return a.x - b.x;
            return a.y - b.y;
        });

        // Рендерим каждое место
        this.places.forEach(place => {
            const placeElement = this.createPlaceElement(place);
            mapGrid.appendChild(placeElement);
        });
    }

    createPlaceElement(place) {
        const div = document.createElement('div');
        div.className = `place ${place.status}`;
        div.dataset.id = place.id;

        // Определяем CSS класс в зависимости от статуса
        if (this.isPlaceBookedByUser(place.id)) {
            div.classList.add('reserved');
        }

        div.innerHTML = `
            <span class="place-number">${place.name.split(' ').pop()}</span>
            <span class="place-type">${this.getPlaceTypeName(place.type)}</span>
            ${place.status === 'occupied' ? '<div class="occupied-badge">Занято</div>' : ''}
        `;

        // Добавляем обработчик клика
        div.addEventListener('click', () => this.selectPlace(place));

        return div;
    }

    getPlaceTypeName(type) {
        const types = {
            'desk': 'Стол',
            'room': 'Комната',
            'office': 'Офис'
        };
        return types[type] || type;
    }

    isPlaceBookedByUser(placeId) {
        return this.userBookings.some(booking =>
            booking.place_id === placeId &&
            booking.status === 'active'
        );
    }

    selectPlace(place) {
        if (place.status === 'occupied' && !this.isPlaceBookedByUser(place.id)) {
            if (typeof showToast === 'function') showToast('Это место уже занято', 'warning');
            return;
        }

        this.selectedPlace = place;
        this.updateSidebar();

        // Подсвечиваем выбранное место
        document.querySelectorAll('.place').forEach(p => {
            p.classList.remove('selected');
        });
        document.querySelector(`.place[data-id="${place.id}"]`).classList.add('selected');
    }

    updateSidebar() {
        if (!this.selectedPlace) return;

        const place = this.selectedPlace;
        const sidebar = document.getElementById('booking-sidebar');
        const form = document.getElementById('booking-form');
        const details = document.getElementById('place-details');
        const placeName = document.getElementById('selected-place-name');

        placeName.textContent = place.name;

        if (place.status === 'free' && !this.isPlaceBookedByUser(place.id)) {
            // Показываем форму бронирования
            form.style.display = 'block';
            details.style.display = 'none';

            // Обновляем информацию о цене
            this.updatePrice();
        } else {
            // Показываем информацию о месте
            form.style.display = 'none';
            details.style.display = 'block';

            document.getElementById('place-type').textContent = this.getPlaceTypeName(place.type);
            document.getElementById('place-price').textContent = place.price_per_hour;
            document.getElementById('place-rating').textContent = place.rating.toFixed(1);
            document.getElementById('place-status').textContent = this.getStatusName(place.status);
        }
    }

    getStatusName(status) {
        const statuses = {
            'free': 'Свободно',
            'occupied': 'Занято',
            'reserved': 'Забронировано вами',
            'maintenance': 'На обслуживании'
        };
        return statuses[status] || status;
    }

    updatePrice() {
        if (!this.selectedPlace) return;

        const startInput = document.getElementById('start-time');
        const endInput = document.getElementById('end-time');
        const priceDisplay = document.getElementById('booking-price');

        if (!startInput.value || !endInput.value) return;

        const startTime = new Date(startInput.value);
        const endTime = new Date(endInput.value);

        // Проверка, что дата окончания позже даты начала
        if (endTime <= startTime) {
            priceDisplay.textContent = '0';
            return;
        }

        // Расчет стоимости
        const hours = (endTime - startTime) / (1000 * 60 * 60);
        const price = hours * this.selectedPlace.price_per_hour;

        priceDisplay.textContent = price.toFixed(2);
    }

    setupEventListeners() {
        // Обновление карты
        document.getElementById('refresh-map-btn')?.addEventListener('click', () => {
            this.refreshMap();
        });

        // Отмена выбора места
        document.getElementById('cancel-booking-btn')?.addEventListener('click', () => {
            this.selectedPlace = null;
            document.getElementById('booking-form').style.display = 'none';
            document.getElementById('place-details').style.display = 'none';
            document.getElementById('selected-place-name').textContent = 'Выберите место на карте';

            document.querySelectorAll('.place').forEach(p => {
                p.classList.remove('selected');
            });
        });

        // Подтверждение бронирования
        document.getElementById('confirm-booking-btn')?.addEventListener('click', () => {
            this.createBooking();
        });

        // Слушатели для изменения времени
        document.getElementById('start-time')?.addEventListener('change', () => {
            this.updatePrice();
            this.adjustEndTime();
        });

        document.getElementById('end-time')?.addEventListener('change', () => {
            this.updatePrice();
        });
    }

    adjustEndTime() {
        const startInput = document.getElementById('start-time');
        const endInput = document.getElementById('end-time');

        if (!startInput.value) return;

        const startTime = new Date(startInput.value);
        const defaultEndTime = new Date(startTime.getTime() + 2 * 60 * 60 * 1000);

        // Округляем до получаса
        defaultEndTime.setMinutes(defaultEndTime.getMinutes() - (defaultEndTime.getMinutes() % 30));

        endInput.min = startInput.value;
        endInput.value = defaultEndTime.toISOString().slice(0, 16);

        this.updatePrice();
    }

    async createBooking() {
        if (!this.selectedPlace) return;

        const startTime = document.getElementById('start-time').value;
        const endTime = document.getElementById('end-time').value;

        if (!startTime || !endTime) {
            if (typeof showToast === 'function') showToast('Пожалуйста, выберите время начала и окончания', 'warning');
            return;
        }

        const bookingData = {
            place_id: this.selectedPlace.id,
            start_time: startTime,
            end_time: endTime
        };

        try {
            const response = await fetch('/api/bookings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(bookingData)
            });

            const data = await response.json();

            if (response.ok) {
                if (typeof showToast === 'function') showToast(`Бронирование успешно создано! Стоимость: ${data.total_price} ₽`, 'success');
                this.refreshMap();
                this.selectedPlace = null;
                document.getElementById('booking-form').style.display = 'none';
                document.getElementById('selected-place-name').textContent = 'Выберите место на карте';
            } else {
                if (typeof showToast === 'function') showToast('Ошибка: ' + data.error, 'error');
            }
        } catch (error) {
            console.error('Error:', error);
            if (typeof showToast === 'function') showToast('Произошла ошибка при создании бронирования', 'error');
        }
    }

    async refreshMap() {
        try {
            const response = await fetch('/api/places');
            this.places = await response.json();
            this.renderMap();
        } catch (error) {
            console.error('Error refreshing map:', error);
        }
    }

    async loadUserBookings() {
        try {
            const response = await fetch('/api/my-bookings');
            if (response.ok) {
                this.userBookings = await response.json();
            }
        } catch (error) {
            console.error('Error loading user bookings:', error);
        }
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('map-grid')) {
        window.mapManager = new MapManager();
    }
});