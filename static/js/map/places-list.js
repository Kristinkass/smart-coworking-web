/**
 * Список мест на странице карты (режим «Список»).
 */
'use strict';

let currentUserView = 'map';
let listActiveZoneCode = null;

function isMobileViewport() {
    return window.matchMedia('(max-width: 768px)').matches;
}

function applyMobileLayout() {
    document.body.classList.remove('mobile-no-map');
    const mapToggle = document.querySelector('.view-mode-switch');
    if (mapToggle) mapToggle.style.display = '';
}

function setUserView(view) {
    currentUserView = view;
    const isMap = view === 'map';
    const mapPanel = document.getElementById('map-view-panel');
    const listContainer = document.getElementById('places-list-view');
    const managerList = document.getElementById('manager-status-list');
    const mapBtn = document.getElementById('map-view-btn');
    const listBtn = document.getElementById('list-view-btn');
    const isStaff = typeof IS_STAFF !== 'undefined' && IS_STAFF;

    if (isMap) {
        listActiveZoneCode = null;
    }

    if (!isMap && typeof activeSpace !== 'undefined' && activeSpace) {
        if (typeof exitSpaceView === 'function') {
            exitSpaceView();
        } else {
            activeSpace = null;
        }
    }

    if (mapPanel) {
        mapPanel.classList.toggle('map-view-hidden', !isMap);
        mapPanel.style.display = isMap ? 'block' : 'none';
    }

    document.querySelectorAll('.map-only-view').forEach(el => {
        if (el.id === 'space-view-bar' || el.id === 'map-view-panel') return;
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
    if (bookingForm && !isMap && !isMobileViewport()) {
        bookingForm.style.display = 'none';
    }

    if (isStaff && managerList) {
        managerList.style.display = 'none';
        managerList.classList.add('map-view-hidden');
    } else if (managerList) {
        managerList.classList.add('map-view-hidden');
        managerList.style.display = 'none';
    }

    if (typeof updateSpaceViewBar === 'function') {
        updateSpaceViewBar();
    }

    if (isMap && isStaff && typeof updateManagerStatusList === 'function') {
        updateManagerStatusList();
    }
}

function isDeskZoneContainer(place) {
    if (!place || place.is_meeting_room) return false;
    if (place.kind !== 'space' && place.kind !== 'room') return false;
    if (place.allows_desks === false) return false;
    if (typeof desksInSpace === 'function') {
        const children = desksInSpace(place).filter(d => !d.is_amenity && d.bookable !== false);
        return children.length > 0;
    }
    return (place.children_count || 0) > 0;
}

function desksInZone(containerCode) {
    return (window.allPlaces || []).filter(p =>
        p.container_code === containerCode &&
        p.kind === 'desk' &&
        !p.is_amenity &&
        p.bookable !== false &&
        (p.floor || 1) === (typeof currentFloor !== 'undefined' ? currentFloor : 1)
    );
}

function placesForListSelection() {
    if (listActiveZoneCode) {
        return desksInZone(listActiveZoneCode);
    }

    return (window.allPlaces || []).filter(p => {
        if ((p.floor || 1) !== (typeof currentFloor !== 'undefined' ? currentFloor : 1)) return false;
        if (p.container_code) return false;
        if (p.is_amenity || p.bookable === false) return false;
        const isOrphan = p.kind === 'desk' && !p.container_code;
        const isContainer = p.kind === 'space' || p.kind === 'room';
        return isOrphan || isContainer;
    });
}

function openListZone(zoneCode) {
    listActiveZoneCode = zoneCode;
    renderPlacesList();
}

function exitListZone() {
    listActiveZoneCode = null;
    renderPlacesList();
}

function listPriceLabel(place) {
    if (place.show_list_price === false) return '';
    const price = place.price_per_hour ?? place.category?.hourly_price;
    if (price == null || price === '') return '';
    return ` · ${Math.round(Number(price))} ₽/ч`;
}

function listLocationGroupTitle(place) {
    if (place.is_meeting_room || place.kind === 'room') return 'Переговорные';
    if (isDeskZoneContainer(place)) return 'Рабочие зоны';
    if (place.kind === 'desk') return 'Рабочие столы';
    return 'Другие места';
}

const LIST_GROUP_ORDER = ['Рабочие столы', 'Рабочие зоны', 'Переговорные', 'Другие места'];

function listPriceForSort(place) {
    if (place.show_list_price === false) return null;
    const price = place.price_per_hour ?? place.category?.hourly_price;
    return price != null ? Number(price) : null;
}

function renderPlaceListItem(place) {
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
    const title = (place.name || '').trim() || fullCode;
    const codeHint = fullCode && fullCode !== title
        ? `<span class="place-list-code-sub">${fullCode}</span>`
        : '';
    const ratingText = place.rating && place.rating > 0
        ? `<span class="places-list-rating"><i class="fas fa-star"></i> ${place.rating.toFixed(1)}</span>`
        : '<span class="places-list-no-rating">Нет оценок</span>';

    const zoneHint = isDeskZoneContainer(place)
        ? '<span class="places-list-zone-hint"><i class="fas fa-chevron-right"></i> Выбрать стол</span>'
        : '';

    const capacity = typeof displayCapacity === 'function' ? displayCapacity(place) : (place.capacity || 1);
    const deskCount = isDeskZoneContainer(place) && typeof desksInSpace === 'function'
        ? desksInSpace(place).filter(d => !d.is_amenity && d.bookable !== false).length
        : 0;
    const metaExtra = deskCount ? ` · ${deskCount} столов` : '';

    return `
    <div class="place-list-item ${statusClass}${isDeskZoneContainer(place) ? ' place-list-zone' : ''}"
         onclick="selectPlaceFromList('${place.code}')">
        <div class="place-list-item-header">
            <span class="place-list-code">${title}${codeHint}</span>
            <span class="place-list-status" style="color:${statusColor}">${statusText}</span>
        </div>
        <div class="place-list-meta">
            <span>${capacity} мест${place.size_label ? ' · ' + place.size_label : ''}${metaExtra}${listPriceLabel(place)}</span>
            <span>${ratingText}${zoneHint}</span>
        </div>
    </div>`;
}

function renderPlacesList() {
    const container = document.getElementById('places-list-content');
    const zoneBar = document.getElementById('list-zone-bar');
    const zoneTitle = document.getElementById('list-zone-title');
    const filters = document.getElementById('places-list-filters');
    const source = window.allPlaces || [];

    if (!container) return;
    if (!source.length) {
        container.innerHTML = '<div class="places-list-empty">Загрузка мест...</div>';
        return;
    }

    if (listActiveZoneCode) {
        const zone = source.find(p => p.code === listActiveZoneCode);
        if (zoneBar) zoneBar.style.display = 'flex';
        if (zoneTitle) zoneTitle.textContent = zone ? zone.name : listActiveZoneCode;
        if (filters) filters.style.display = 'none';
    } else {
        if (zoneBar) zoneBar.style.display = 'none';
        if (filters) filters.style.display = 'flex';
    }

    const kindFilter = document.getElementById('list-filter-kind')?.value || 'all';
    const priceSort = document.getElementById('list-sort-price')?.value || 'none';
    const ratingSort = document.getElementById('list-sort-rating')?.value || 'none';

    let filtered = placesForListSelection().filter(p => {
        if (listActiveZoneCode) return true;
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
            const pa = listPriceForSort(a);
            const pb = listPriceForSort(b);
            if (pa == null && pb == null) return 0;
            if (pa == null) return 1;
            if (pb == null) return -1;
            return priceSort === 'asc' ? pa - pb : pb - pa;
        });
    }
    if (ratingSort === 'desc') {
        filtered.sort((a, b) => (b.rating || 0) - (a.rating || 0));
    }

    if (filtered.length === 0) {
        container.innerHTML = listActiveZoneCode
            ? '<div class="places-list-empty">В этой зоне нет доступных столов</div>'
            : '<div class="places-list-empty">Нет доступных мест по выбранным фильтрам</div>';
        return;
    }

    if (listActiveZoneCode) {
        container.innerHTML = `<div class="places-list-grid">${filtered.map(renderPlaceListItem).join('')}</div>`;
        return;
    }

    const byGroup = {};
    filtered.forEach(p => {
        const group = listLocationGroupTitle(p);
        if (!byGroup[group]) byGroup[group] = [];
        byGroup[group].push(p);
    });

    let html = '';
    LIST_GROUP_ORDER.filter(g => byGroup[g]?.length).forEach(group => {
        html += `<div class="places-list-group"><h4 class="places-list-group-title">${group}</h4><div class="places-list-grid">`;
        html += byGroup[group].map(renderPlaceListItem).join('');
        html += '</div></div>';
    });

    container.innerHTML = html;
}

function selectPlaceForBookingFromList(place) {
    if (typeof selectPlaceForBooking === 'function') {
        selectPlaceForBooking(place);
    }
}

function selectPlaceFromList(placeCode) {
    const place = (window.allPlaces || []).find(p => p.code === placeCode);
    if (!place) return;

    if (place.maintenance || place.status === 'maintenance') {
        if (typeof showAlert === 'function') showAlert('Это место на обслуживании', 'warning');
        return;
    }

    if (isDeskZoneContainer(place)) {
        openListZone(place.code);
        return;
    }

    selectPlaceForBookingFromList(place);
}

window.addEventListener('resize', applyMobileLayout);
