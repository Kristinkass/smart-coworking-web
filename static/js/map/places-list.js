/**
 * Список мест на странице карты (режим «Список»).
 */
'use strict';

let currentUserView = 'map';

function setUserView(view) {
    currentUserView = view;
    const isMap = view === 'map';
    const listContainer = document.getElementById('places-list-view');
    const managerList = document.getElementById('manager-status-list');
    const mapBtn = document.getElementById('map-view-btn');
    const listBtn = document.getElementById('list-view-btn');
    const isStaff = typeof IS_STAFF !== 'undefined' && IS_STAFF;

    document.querySelectorAll('.map-only-view').forEach(el => {
        el.classList.toggle('map-view-hidden', !isMap);
        el.style.display = isMap ? '' : 'none';
    });

    mapBtn?.classList.toggle('active', isMap);
    listBtn?.classList.toggle('active', !isMap);

    if (listContainer) {
        listContainer.classList.toggle('map-view-hidden', isMap);
        listContainer.style.display = isMap ? 'none' : 'block';
        if (!isMap) renderPlacesList();
    }

    const bookingForm = document.getElementById('booking-form');
    if (bookingForm && !isMap) {
        bookingForm.style.display = 'none';
    }

    if (isStaff && managerList) {
        managerList.classList.toggle('map-view-hidden', !isMap);
        managerList.style.display = isMap ? '' : 'none';
    } else if (managerList) {
        managerList.classList.add('map-view-hidden');
        managerList.style.display = 'none';
    }

    if (isMap && isStaff && typeof updateManagerStatusList === 'function') {
        updateManagerStatusList();
    }
}

function placesForListSelection() {
    return (window.allPlaces || []).filter(p => {
        if ((p.floor || 1) !== currentFloor) return false;
        if (p.container_code) return false;
        if (p.is_amenity || p.bookable === false) return false;
        const isOrphan = p.kind === 'desk' && !p.container_code;
        const isContainer = p.kind === 'space' || p.kind === 'room';
        return isOrphan || isContainer;
    });
}

function renderPlacesList() {
    const container = document.getElementById('places-list-content');
    const source = window.allPlaces || [];
    if (!container) return;
    if (!source.length) {
        container.innerHTML = '<div class="places-list-empty">Загрузка мест...</div>';
        return;
    }

    const kindFilter = document.getElementById('list-filter-kind')?.value || 'all';
    const priceSort = document.getElementById('list-sort-price')?.value || 'none';
    const ratingSort = document.getElementById('list-sort-rating')?.value || 'none';

    let filtered = placesForListSelection().filter(p => {
        if (kindFilter === 'desk') {
            return p.kind === 'desk' || (p.kind === 'space' && p.allows_desks !== false && !p.is_meeting_room);
        }
        if (kindFilter === 'room') {
            return p.kind === 'room' || p.is_meeting_room;
        }
        return true;
    });

    if (priceSort !== 'none') {
        filtered.sort((a, b) => {
            const pa = a.price_per_hour || 0;
            const pb = b.price_per_hour || 0;
            return priceSort === 'asc' ? pa - pb : pb - pa;
        });
    }
    if (ratingSort === 'desc') {
        filtered.sort((a, b) => (b.rating || 0) - (a.rating || 0));
    }

    if (filtered.length === 0) {
        container.innerHTML = '<div class="places-list-empty">Нет доступных мест по выбранным фильтрам</div>';
        return;
    }

    const byLocation = {};
    filtered.forEach(p => {
        const locCode = p.location_code || 'Другое';
        if (!byLocation[locCode]) byLocation[locCode] = [];
        byLocation[locCode].push(p);
    });

    let html = '';
    for (const [locCode, places] of Object.entries(byLocation)) {
        html += `<div class="places-list-group"><h4 class="places-list-group-title">Локация ${locCode}</h4><div class="places-list-grid">`;

        places.forEach(place => {
            const isOccupied = place.status === 'occupied';
            const isPartial = place.status === 'partial';
            const isMaintenance = place.status === 'maintenance';
            let statusClass = 'free';
            let statusText = 'Свободно';
            let statusColor = '#4d8f5f';

            if (isOccupied) {
                statusClass = 'occupied';
                statusText = 'Занято';
                statusColor = '#c75050';
            } else if (isPartial) {
                statusClass = 'partial';
                statusText = place.partial_occupancy
                    ? `Частично (${place.partial_occupancy.occupied}/${place.partial_occupancy.capacity})`
                    : 'Частично';
                statusColor = '#d97706';
            } else if (isMaintenance) {
                statusClass = 'maintenance';
                statusText = 'Обслуживание';
                statusColor = '#6b7280';
            }

            const fullCode = formatPlaceCode(place);
            const ratingText = place.rating && place.rating > 0
                ? `<span class="places-list-rating"><i class="fas fa-star"></i> ${place.rating.toFixed(1)}</span>`
                : '<span class="places-list-no-rating">Нет оценок</span>';

            html += `
            <div class="place-list-item ${statusClass}"
                 onclick="selectPlaceFromList('${place.code}')">
                <div class="place-list-item-header">
                    <span class="place-list-code">${fullCode}</span>
                    <span class="place-list-status" style="color:${statusColor}">${statusText}</span>
                </div>
                <div class="place-list-name">${place.name}</div>
                <div class="place-list-meta">
                    <span>${(typeof displayCapacity === 'function' ? displayCapacity(place) : (place.capacity || 1))} мест${place.size_label ? ' · ' + place.size_label : ''} · ${place.price_per_hour || 0} ₽/ч</span>
                    <span>${ratingText}</span>
                </div>
            </div>
            `;
        });

        html += '</div></div>';
    }

    container.innerHTML = html;
}

function selectPlaceFromList(placeCode) {
    const place = (window.allPlaces || []).find(p => p.code === placeCode);
    if (!place) return;

    if (place.maintenance || place.status === 'maintenance') {
        if (typeof showAlert === 'function') showAlert('Это место на обслуживании', 'warning');
        return;
    }

    setUserView('map');
    if (typeof handlePlaceClick === 'function') {
        handlePlaceClick(place);
    } else if (typeof selectPlaceByCode === 'function') {
        selectPlaceByCode(placeCode);
    }
}
