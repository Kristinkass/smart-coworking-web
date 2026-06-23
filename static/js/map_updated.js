// ================== КАРТА КОВОРКИНГА – map_updated.js ==================
'use strict';

let places = [];
let selectedPlace = null;
let editMode = false;
let editSelectedPlace = null;
let wallsData = [];
let doorsData = [];
let currentFloor = 1;
const DEFAULT_MAP_ZOOM = 1;
let zoomLevel = DEFAULT_MAP_ZOOM;
let spaceEntryZoomLevel = null;
let activeSpace = null; // Просмотр внутри помещения
let userSubscriptions = []; // Активные абонементы пользователя
window.allPlaces = [];

// Индексы мест (пересчитываются в buildPlaceIndexes после loadPlaces)
let desksBySpaceCode = Object.create(null);
let deskSpaceByDeskId = new Map();
let childCountBySpaceCode = Object.create(null);
let zoneSeatCapacityBySpaceCode = Object.create(null);
let wallsByFloor = Object.create(null);
let doorsByFloor = Object.create(null);
let placesByIdMap = new Map();
let _viewPlacesCache = null;
let _viewPlacesCacheKey = '';

function invalidateViewCache() {
    _viewPlacesCache = null;
    _viewPlacesCacheKey = '';
}

function deskBelongsToSpaceGeometric(desk, space) {
    if (!desk || !space || !isDesk(desk) || !isSpaceContainer(space)) return false;
    if (Number(desk.floor || 1) !== Number(space.floor || 1)) return false;
    if (desk.container_code === space.code) return true;
    const cx = desk.x + desk.width / 2;
    const cy = desk.y + desk.height / 2;
    return cx >= space.x && cx <= space.x + space.width
        && cy >= space.y && cy <= space.y + space.height;
}

function buildPlaceIndexes() {
    desksBySpaceCode = Object.create(null);
    deskSpaceByDeskId = new Map();
    childCountBySpaceCode = Object.create(null);
    zoneSeatCapacityBySpaceCode = Object.create(null);
    wallsByFloor = Object.create(null);
    doorsByFloor = Object.create(null);
    placesByIdMap = new Map(places.map(p => [p.id, p]));
    invalidateViewCache();

    const spacesByFloor = Object.create(null);
    const allDesks = [];

    places.forEach(place => {
        const floor = Number(place.floor || 1);
        if (isSpaceContainer(place)) {
            if (!spacesByFloor[floor]) spacesByFloor[floor] = [];
            spacesByFloor[floor].push(place);
        } else if (isDesk(place)) {
            allDesks.push(place);
        }
    });

    allDesks.forEach(desk => {
        let spaceCode = desk.container_code;
        if (!spaceCode) {
            const floor = Number(desk.floor || 1);
            const spaces = spacesByFloor[floor] || [];
            for (let i = 0; i < spaces.length; i++) {
                if (deskBelongsToSpaceGeometric(desk, spaces[i])) {
                    spaceCode = spaces[i].code;
                    deskSpaceByDeskId.set(desk.id, spaces[i]);
                    break;
                }
            }
        } else {
            const space = places.find(p => p.code === spaceCode);
            if (space) deskSpaceByDeskId.set(desk.id, space);
        }
        if (!spaceCode) return;
        if (!desksBySpaceCode[spaceCode]) desksBySpaceCode[spaceCode] = [];
        desksBySpaceCode[spaceCode].push(desk);
    });

    Object.keys(desksBySpaceCode).forEach(code => {
        const list = desksBySpaceCode[code];
        childCountBySpaceCode[code] = list.length;
        zoneSeatCapacityBySpaceCode[code] = list.reduce((sum, d) => sum + (d.capacity || 1), 0);
    });

    wallsData.forEach(w => {
        const floor = Number(w.floor || 1);
        if (!wallsByFloor[floor]) wallsByFloor[floor] = [];
        wallsByFloor[floor].push(w);
    });
    doorsData.forEach(d => {
        const floor = Number(d.floor || 1);
        if (!doorsByFloor[floor]) doorsByFloor[floor] = [];
        doorsByFloor[floor].push(d);
    });
}

function desksInSpace(space) {
    if (!space || !space.code) return [];
    return desksBySpaceCode[space.code] || [];
}

// ---- Статус места для отображения ----
function effectivePlaceStatus(place) {
    if (place.maintenance) return 'maintenance';
    if (place.partial_occupancy && place.partial_occupancy.occupied < place.partial_occupancy.capacity) {
        return 'partial';
    }
    if (place.status === 'partial') return 'partial';
    if (place.current_occupancy > 0 && place.capacity > 1 && place.current_occupancy < place.capacity) {
        return 'partial';
    }
    if (place.status === 'occupied') return 'occupied';
    return place.status || 'free';
}

// ---- Помещения и карта ----
function isSpaceContainer(place) {
    return place.kind === 'space' || place.kind === 'room';
}

function isFloorWideZone(place) {
    if (!isSpaceContainer(place)) return false;
    if (place.enclosed === true) return false;
    const area = (place.width || 0) * (place.height || 0);
    return area > 2240 * 1344 * 0.45;
}

function isDesk(place) {
    return place.kind === 'desk';
}

function isOrphanDesk(place) {
    return isDesk(place) && !place.container_code;
}

function showDeskOnMap(place) {
    if (!isDesk(place)) return false;
    if (activeSpace || isOrphanDesk(place)) return true;
    return editMode && IS_STAFF;
}

function isAmenityPlace(place) {
    return !!(place && (place.is_amenity || place.bookable === false));
}

function deskBelongsToSpace(desk, space) {
    if (!desk || !space || !isDesk(desk) || !isSpaceContainer(space)) return false;
    if (Number(desk.floor || 1) !== Number(space.floor || 1)) return false;
    if (desk.container_code === space.code) return true;
    const mapped = deskSpaceByDeskId.get(desk.id);
    if (mapped) return mapped.id === space.id;
    return deskBelongsToSpaceGeometric(desk, space);
}

function placesForCurrentView() {
    const cacheKey = `${currentFloor}|${activeSpace?.id || 0}|${editMode ? 1 : 0}|${IS_STAFF ? 1 : 0}`;
    if (_viewPlacesCache && _viewPlacesCacheKey === cacheKey) {
        return _viewPlacesCache;
    }

    const onFloor = places.filter(p => Number(p.floor || 1) === currentFloor);
    let result;

    if (editMode && IS_STAFF) {
        if (activeSpace) {
            const desks = desksInSpace(activeSpace);
            result = onFloor.filter(p =>
                p.id === activeSpace.id || desks.some(d => d.id === p.id)
            );
        } else {
            result = onFloor;
        }
    } else if (activeSpace) {
        result = desksInSpace(activeSpace).filter(p => Number(p.floor || 1) === currentFloor);
    } else {
        result = onFloor.filter(p => {
            if (isOrphanDesk(p)) return true;
            return isSpaceContainer(p) && !p.container_code && !isFloorWideZone(p);
        });
    }

    _viewPlacesCache = result;
    _viewPlacesCacheKey = cacheKey;
    return result;
}

// Текущее время с сервера (или клиентское как запасной вариант)
function getNow() {
    if (typeof SERVER_NOW !== 'undefined' && SERVER_NOW) {
        return new Date(SERVER_NOW);
    }
    return new Date();
}

const KIND_FILL   = { desk: '#bbf7d0', room: '#bae6fd', space: '#bae6fd' };
const KIND_STROKE = { desk: '#16a34a', room: '#0284c7', space: '#0284c7' };
const DESK_ZONE_FILL = '#DDB892';
const DESK_ZONE_STROKE = '#7C5C3A';
const AMENITY_FILL = '#f3e8ff';
const AMENITY_STROKE = '#7e22ce';

function isDeskZoneSpace(place) {
    if (!isSpaceContainer(place)) return false;
    if (place.is_meeting_room) return false;
    if (place.zone_type && place.zone_type.kind === 'room_zone') return false;
    if (place.zone_type && place.zone_type.kind === 'desk_zone') return true;
    return place.allows_desks !== false;
}
const STATUS_OVERLAY = {
    partial:     { fill: '#fde68a', stroke: '#d97706' },
    occupied:    { fill: '#fecaca', stroke: '#dc2626' },
    maintenance: { fill: '#d1d5db', stroke: '#6b7280' }
};

// Время работы коворкинга - динамическое из расписания
function getCoworkingHours() {
    if (window.currentSchedule && window.currentSchedule.open && window.currentSchedule.close) {
        const [openH, openM] = window.currentSchedule.open.split(':').map(Number);
        const closeRaw = window.currentSchedule.close.trim();
        const [closeH, closeM] = closeRaw.split(':').map(Number);
        const open = openH * 60 + openM;
        let close = closeH * 60 + closeM;
        if (closeRaw === '24:00' || (close === 0 && open > 0)) {
            close = 24 * 60;
        }
        return { open, close };
    }
    return { open: 8 * 60, close: 22 * 60 };
}

// ================== МОДАЛЬНЫЕ ОКНА ==================
let modalCallback = null;

function showModal(title, message, type = 'info', callback = null) {
    const modal = document.getElementById('confirm-modal');
    const icon = document.getElementById('modal-icon');
    const titleEl = document.getElementById('modal-title');
    const messageEl = document.getElementById('modal-message');
    const confirmBtn = document.getElementById('modal-confirm-btn');

    const icons = {
        info: '<i class="fas fa-info-circle"></i>',
        warning: '<i class="fas fa-exclamation-triangle"></i>',
        error: '<i class="fas fa-times-circle"></i>',
        success: '<i class="fas fa-check-circle"></i>',
        question: '<i class="fas fa-question-circle"></i>'
    };

    icon.innerHTML = icons[type] || icons.question;
    icon.className = 'modal-icon ' + (type === 'question' ? 'warning' : type);
    titleEl.textContent = title;
    messageEl.textContent = message;

    modalCallback = callback;

    if (callback) {
        confirmBtn.style.display = 'block';
        confirmBtn.textContent = 'Подтвердить';
        confirmBtn.className = type === 'error' ? 'btn-danger' : (type === 'success' ? 'btn-success' : 'btn-confirm');
    } else {
        confirmBtn.style.display = 'none';
    }

    modal.classList.add('active');
}

function showConfirm(message, callback, title = 'Подтверждение') {
    showModal(title, message, 'question', callback);
}

function closeModal() {
    document.getElementById('confirm-modal').classList.remove('active');
    modalCallback = null;
}

function confirmModal() {
    if (modalCallback) {
        modalCallback();
        modalCallback = null;
    }
    closeModal();
}

// Закрытие по клику вне окна
document.addEventListener('click', (e) => {
    const modal = document.getElementById('confirm-modal');
    if (e.target === modal) closeModal();
});

// ================== INIT ==================
document.addEventListener('DOMContentLoaded', function () {
    initTimeSelects();
    setupEventListeners();
    setupMapEventDelegation();
    loadUserSubscriptions();
    const initialParams = new URLSearchParams(window.location.search);
    const initialFloor = parseInt(initialParams.get('floor') || '', 10);
    if (initialFloor) currentFloor = initialFloor;
    loadPlaces().then(() => {
        if (typeof setUserView === 'function') setUserView('map');
        applyInitialMapFocus(initialParams);
    });

    document.getElementById('floor-plan').addEventListener('click', function (e) {
        if (e.target === this || e.target.id === 'places-layer') {
            if (editMode) {
                editSelectedPlace = null;
                document.getElementById('maintenance-panel').classList.remove('active');
                updateEditSelectionHighlight();
            }
        }
    });

    // Скрываем tooltip при скролле
    document.addEventListener('scroll', hideTooltip, true);
});

// ================== ВЫБОР ВРЕМЕНИ (только 15-минутные интервалы) ==================
const SLOT_MINUTES = [0, 15, 30, 45];

function roundUpTo15(totalMinutes) {
    return Math.ceil(totalMinutes / 15) * 15;
}

function fillMinuteSelect(selectEl) {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    ['00', '15', '30', '45'].forEach(mm => {
        const opt = document.createElement('option');
        opt.value = mm;
        opt.textContent = mm;
        selectEl.appendChild(opt);
    });
}

function fillHourSelect(selectEl, hours) {
    if (!selectEl) return;
    const previous = selectEl.value;
    selectEl.innerHTML = '';
    hours.forEach(h => {
        const value = String(h).padStart(2, '0');
        const opt = document.createElement('option');
        opt.value = value;
        opt.textContent = value;
        selectEl.appendChild(opt);
    });
    if (hours.some(h => String(h).padStart(2, '0') === previous)) {
        selectEl.value = previous;
    }
}

function setDisabledOptionValues(selectEl, disabledValues) {
    if (!selectEl) return;
    Array.from(selectEl.options).forEach(opt => {
        const disabled = disabledValues.has(opt.value);
        opt.disabled = disabled;
        opt.hidden = disabled;
    });
}

function minutesToTime(totalMinutes) {
    return String(Math.floor(totalMinutes / 60)).padStart(2, '0') +
        ':' + String(totalMinutes % 60).padStart(2, '0');
}

function timegridSlotAt(totalMinutes) {
    const slots = window.currentBookingTimegrid || [];
    const time = minutesToTime(totalMinutes);
    return slots.find(slot => slot.time === time) || null;
}

const MIN_BOOKING_MINUTES = 30;

function getStartTotalMinutes() {
    const startH = document.getElementById('start-hour');
    const startM = document.getElementById('start-min');
    if (!startH || !startM) return 0;
    return parseInt(startH.value, 10) * 60 + parseInt(startM.value, 10);
}

function getEndTotalMinutes() {
    const endH = document.getElementById('end-hour');
    const endM = document.getElementById('end-min');
    if (!endH || !endM) return 0;
    return parseInt(endH.value, 10) * 60 + parseInt(endM.value, 10);
}

function isEndTimeValid(endTotal, startTotal) {
    const hours = getCoworkingHours();
    if (endTotal <= startTotal || endTotal - startTotal < MIN_BOOKING_MINUTES) return false;
    if (endTotal > hours.close) return false;

    const now = getNow();
    const todayVal = document.getElementById('booking-date')?.value;
    const isToday = todayVal === now.toISOString().split('T')[0];
    if (isToday && endTotal <= roundUpTo15(now.getHours() * 60 + now.getMinutes())) {
        return false;
    }
    return true;
}

function buildEndHourList(hourList, startTotal) {
    return hourList.filter(h =>
        SLOT_MINUTES.some(m => isEndTimeValid(h * 60 + m, startTotal))
    );
}

function firstAvailableStartTotal() {
    const startH = document.getElementById('start-hour');
    if (!startH) return null;
    for (const opt of startH.options) {
        const h = parseInt(opt.value, 10);
        for (const m of SLOT_MINUTES) {
            const total = h * 60 + m;
            if (!isStartTimeUnavailable(total)) return total;
        }
    }
    return null;
}

function firstAvailableEndTotal(startTotal) {
    const hours = getCoworkingHours();
    let candidate = Math.min(startTotal + 60, hours.close);
    candidate = Math.max(candidate, startTotal + MIN_BOOKING_MINUTES);
    candidate = roundUpTo15(candidate);
    if (!isEndTimeValid(candidate, startTotal)) {
        for (let total = startTotal + MIN_BOOKING_MINUTES; total <= hours.close; total += 15) {
            if (isEndTimeValid(total, startTotal)) return total;
        }
        return null;
    }
    return candidate;
}

function setTimeFromTotal(prefix, totalMinutes) {
    const hEl = document.getElementById(`${prefix}-hour`);
    const mEl = document.getElementById(`${prefix}-min`);
    if (!hEl || !mEl || totalMinutes == null) return;
    hEl.value = String(Math.floor(totalMinutes / 60)).padStart(2, '0');
    mEl.value = String(totalMinutes % 60).padStart(2, '0');
}

function rebuildEndHourSelect() {
    const startH = document.getElementById('start-hour');
    const endH = document.getElementById('end-hour');
    if (!startH || !endH || !startH.options.length) return false;

    const hourList = Array.from(startH.options).map(opt => parseInt(opt.value, 10));
    const startTotal = getStartTotalMinutes();
    const endHourList = buildEndHourList(hourList, startTotal);
    if (!endHourList.length) return false;

    const prevEndH = endH.value;
    fillHourSelect(endH, endHourList);
    if (endHourList.some(h => String(h).padStart(2, '0') === prevEndH)) {
        endH.value = prevEndH;
    }
    return true;
}

function ensureValidBookingTimeRange() {
    const startH = document.getElementById('start-hour');
    const endH = document.getElementById('end-hour');
    if (!startH || !endH || !startH.options.length) return false;

    let startTotal = getStartTotalMinutes();
    if (isStartTimeUnavailable(startTotal)) {
        startTotal = firstAvailableStartTotal();
        if (startTotal == null) return false;
        setTimeFromTotal('start', startTotal);
    }

    if (!rebuildEndHourSelect()) return false;

    const validStartTotal = getStartTotalMinutes();
    let endTotal = getEndTotalMinutes();
    if (!isEndTimeValid(endTotal, validStartTotal)) {
        endTotal = firstAvailableEndTotal(startTotal);
        if (endTotal == null) return false;
        setTimeFromTotal('end', endTotal);
    }

    applyMinuteFilters();
    return true;
}

function applyMinuteFilters() {
    const startH = document.getElementById('start-hour');
    const startM = document.getElementById('start-min');
    const endH = document.getElementById('end-hour');
    const endM = document.getElementById('end-min');
    if (!startH || !startM) return;

    const selH = parseInt(startH.value, 10) * 60;

    const disabledStartMinutes = new Set();
    ['00', '15', '30', '45'].forEach(mm => {
        const m = parseInt(mm, 10);
        if (isStartTimeUnavailable(selH + m)) disabledStartMinutes.add(mm);
    });
    setDisabledOptionValues(startM, disabledStartMinutes);
    if (window.ClockTimePicker) ClockTimePicker.setDisabledMinutes('start', disabledStartMinutes);

    if (disabledStartMinutes.has(startM.value)) {
        startM.value = firstEnabledOption(startM) || startM.value;
    }

    if (endH && endM) {
        const startTotal = getStartTotalMinutes();
        rebuildEndHourSelect();
        const disabledEndMinutes = new Set();
        ['00', '15', '30', '45'].forEach(mm => {
            const m = parseInt(mm, 10);
            const endTotal = parseInt(endH.value, 10) * 60 + m;
            if (!isEndTimeValid(endTotal, startTotal)) disabledEndMinutes.add(mm);
        });
        setDisabledOptionValues(endM, disabledEndMinutes);
        if (disabledEndMinutes.has(endM.value)) {
            endM.value = firstEnabledOption(endM) || endM.value;
        }
        if (window.ClockTimePicker) ClockTimePicker.setDisabledMinutes('end', disabledEndMinutes);
    }

    if (window.ClockTimePicker) ClockTimePicker.refresh();
}

function filterPastMinuteOptions() {
    ensureValidBookingTimeRange();
}

function isStartTimeUnavailable(totalMinutes) {
    const hours = getCoworkingHours();
    if (totalMinutes < hours.open || totalMinutes >= hours.close) return true;

    const now = getNow();
    const todayVal = document.getElementById('booking-date')?.value;
    const isToday = todayVal === now.toISOString().split('T')[0];
    if (isToday && totalMinutes < roundUpTo15(now.getHours() * 60 + now.getMinutes())) {
        return true;
    }

    if (window.currentBookingTimegrid && window.currentBookingTimegrid.length) {
        const slot = timegridSlotAt(totalMinutes);
        if (!slot) return true;
        if (slot.is_past) return true;
        if (slot.status === 'full' || slot.available <= 0) return true;
    }

    return false;
}

function firstEnabledOption(selectEl) {
    return Array.from(selectEl?.options || []).find(opt => !opt.disabled)?.value || null;
}

function onBookingDateChange() {
    const dateEl = document.getElementById('booking-date');
    if (dateEl) filterPastHours(dateEl.value);
    if (typeof loadTimegrid === 'function' && selectedPlace && dateEl?.value) {
        loadTimegrid(selectedPlace.id, dateEl.value);
    }
    updateBookingPeriodDisplay();
    schedulePriceDisplayUpdate();
}

function rebuildTimeSelects(openTimeStr, closeTimeStr) {
    const startH = document.getElementById('start-hour');
    const endH = document.getElementById('end-hour');
    const startM = document.getElementById('start-min');
    const endM = document.getElementById('end-min');
    if (!startH || !endH) return;

    const hours = getCoworkingHours();
    const openHour = openTimeStr ? parseInt(openTimeStr.split(':')[0], 10) : Math.floor(hours.open / 60);
    const closeHour = closeTimeStr ? parseInt(closeTimeStr.split(':')[0], 10) : Math.floor(hours.close / 60);

    const now = getNow();
    const todayVal = document.getElementById('booking-date')?.value;
    const isToday = todayVal === now.toISOString().split('T')[0];
    const nowTotal = now.getHours() * 60 + now.getMinutes();
    const nowRounded = roundUpTo15(nowTotal);

    const prevStart = startH.value;
    const prevEnd = endH.value;
    const prevStartM = startM.value;
    const prevEndM = endM.value;

    const hourList = [];
    for (let h = openHour; h <= closeHour; h++) hourList.push(h);

    const startHourList = hourList.filter(h =>
        SLOT_MINUTES.some(m => !isStartTimeUnavailable(h * 60 + m))
    );

    if (!startHourList.length) {
        fillHourSelect(startH, []);
        fillHourSelect(endH, []);
        fillMinuteSelect(startM);
        fillMinuteSelect(endM);
        if (window.ClockTimePicker) {
            ClockTimePicker.setAvailableHours('start', []);
            ClockTimePicker.setAvailableHours('end', []);
            ClockTimePicker.refresh();
        }
        if (typeof showScheduleStatus === 'function') {
            showScheduleStatus('Нет доступного будущего времени для бронирования', 'error');
        }
        if (typeof setBookingTimeControlsEnabled === 'function') {
            setBookingTimeControlsEnabled(false);
        }
        return;
    }

    fillHourSelect(startH, startHourList);
    fillMinuteSelect(startM);
    fillMinuteSelect(endM);

    let defaultStart = null;
    for (const h of startHourList) {
        const minute = SLOT_MINUTES.find(m => !isStartTimeUnavailable(h * 60 + m));
        if (minute != null) {
            defaultStart = h * 60 + minute;
            break;
        }
    }
    if (defaultStart == null) {
        defaultStart = roundUpTo15(isToday ? Math.max(openHour * 60, nowTotal) : openHour * 60 + 60);
    }
    if (defaultStart >= hours.close) defaultStart = Math.max(openHour * 60, hours.close - 60);
    const defaultEnd = Math.min(defaultStart + 60, hours.close);

    const defaultStartM = String(defaultStart % 60).padStart(2, '0');
    const defaultEndM = String(defaultEnd % 60).padStart(2, '0');

    const pickHourValue = (preferred, fallback, sourceHours) => {
        const p = parseInt(preferred, 10);
        if (preferred && sourceHours.includes(p)) return preferred;
        const enabled = sourceHours[0];
        return enabled != null ? String(enabled).padStart(2, '0') : fallback;
    };

    const defaultStartH = String(Math.floor(defaultStart / 60)).padStart(2, '0');
    const defaultEndH = String(Math.floor(defaultEnd / 60)).padStart(2, '0');

    startH.value = pickHourValue(prevStart, defaultStartH, startHourList);
    startM.value = ['00', '15', '30', '45'].includes(prevStartM) ? prevStartM : defaultStartM;
    if (isStartTimeUnavailable(getStartTotalMinutes())) {
        setTimeFromTotal('start', defaultStart);
    }

    const endHourList = buildEndHourList(hourList, getStartTotalMinutes());
    if (!endHourList.length) {
        fillHourSelect(endH, []);
        if (window.ClockTimePicker) {
            ClockTimePicker.setAvailableHours('start', startHourList);
            ClockTimePicker.setAvailableHours('end', []);
            ClockTimePicker.refresh();
        }
        if (typeof showScheduleStatus === 'function') {
            showScheduleStatus('Нет доступного будущего времени для бронирования', 'error');
        }
        if (typeof setBookingTimeControlsEnabled === 'function') {
            setBookingTimeControlsEnabled(false);
        }
        return;
    }

    fillHourSelect(endH, endHourList);
    if (window.ClockTimePicker) {
        ClockTimePicker.setAvailableHours('start', startHourList);
        ClockTimePicker.setAvailableHours('end', endHourList);
        ClockTimePicker.setDisabledHours('start', new Set());
        ClockTimePicker.setDisabledHours('end', new Set());
    }

    endH.value = pickHourValue(prevEnd, defaultEndH, endHourList);
    endM.value = ['00', '15', '30', '45'].includes(prevEndM) ? prevEndM : defaultEndM;

    ensureValidBookingTimeRange();
    if (window.ClockTimePicker) ClockTimePicker.refresh();
    if (typeof syncTimelineWithSelects === 'function') syncTimelineWithSelects();
}

function initTimeSelects() {
    // Часы подставляются после loadTimegrid по расписанию коворкинга
    if (typeof updateDurationDisplay === 'function') updateDurationDisplay();
}

function onTimeChange() {
    ensureValidBookingTimeRange();
    if (typeof syncTimelineWithSelects === 'function') syncTimelineWithSelects();
    if (typeof updateDurationDisplay === 'function') updateDurationDisplay();
    schedulePriceDisplayUpdate();
}

function onPeopleCountChange() {
    document.getElementById('people-count-display').textContent =
        document.getElementById('people-count')?.value || '1';
    schedulePriceDisplayUpdate();
}

function getStartTime() {
    const h = document.getElementById('start-hour')?.value || '09';
    const m = document.getElementById('start-min')?.value  || '00';
    return h + ':' + m;
}

function getEndTime() {
    const h = document.getElementById('end-hour')?.value || '10';
    const m = document.getElementById('end-min')?.value  || '00';
    return h + ':' + m;
}

function getBookingDate() {
    return document.getElementById('booking-date')?.value || '';
}

// ================== УВЕДОМЛЕНИЯ ==================
function showAlert(message, type = 'info') {
    const container = document.getElementById('flashes-container');
    const id = 'alert-' + Date.now();
    const el = document.createElement('div');
    el.className = 'alert alert-' + type;
    el.id = id;
    el.innerHTML =
        '<div class="alert-content">' + message + '</div>' +
        '<button class="alert-close" onclick="closeAlert(\'' + id + '\')">&times;</button>' +
        '<div class="alert-progress"></div>';
    container.appendChild(el);
    setTimeout(() => closeAlert(id), 6000);
}

function showBookingSuccess(placeName, date, startTime, endTime, price, tariffType) {
    tariffType = tariffType || document.getElementById('tariff-type')?.value || 'hourly';
    const isFixed = tariffType === 'weekly' || tariffType === 'monthly';
    const dateLine = formatBookingPeriod(date, tariffType);
    const timeLine = isFixed
        ? `${startTime} - ${endTime} (весь день)<br>`
        : `${startTime} - ${endTime}<br>`;
    const msg = `<strong>Бронирование подтверждено!</strong>
        <b>${placeName}</b><br>
        ${dateLine}<br>
        ${timeLine}
        Стоимость: ${formatRubles(price)}<br>
        <i style="color:#4d8f5f;">Ждём вас! Хорошей работы!</i>`;
    showAlert(msg, 'success');
}

function closeAlert(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add('hiding');
    setTimeout(() => el?.parentNode?.removeChild(el), 350);
}

// ================== TOOLTIP ==================
let tooltipRaf = null;
let tooltipPending = null;

function showTooltip(place, mouseX, mouseY) {
    tooltipPending = { place, mouseX, mouseY };
    if (tooltipRaf) return;
    tooltipRaf = requestAnimationFrame(() => {
        tooltipRaf = null;
        if (!tooltipPending) return;
        const { place: p, mouseX: x, mouseY: y } = tooltipPending;
        tooltipPending = null;
        renderTooltipContent(p, x, y);
    });
}

function renderTooltipContent(place, mouseX, mouseY) {
    const tt = document.getElementById('place-tooltip');
    if (!tt) return;

    const nameText = placeDisplayName(place);
    const codeText = formatPlaceCode(place);
    document.getElementById('tt-name').textContent = nameText;
    const kindEl = document.getElementById('tt-kind');
    if (kindEl) {
        const kind = placeTypeLabel(place);
        kindEl.textContent = codeText && codeText !== nameText ? `${kind} · ${codeText}` : kind;
    }
    
    // Количество мест зоны (не путать с «1 бронь на всю зону»)
    let capText = displayCapacity(place) + ' мест';
    if (place.partial_occupancy) {
        capText += ` (${place.partial_occupancy.occupied} занято, ${place.partial_occupancy.available} свободно)`;
    }
    document.getElementById('tt-cap').textContent = capText;

    const ratingRow = document.getElementById('tt-rating-row');
    if (place.rating && place.rating > 0) {
        document.getElementById('tt-rating').textContent = '★'.repeat(Math.floor(place.rating)) + ' ' + Number(place.rating).toFixed(1);
        ratingRow.style.display = 'flex';
    } else {
        ratingRow.style.display = 'none';
    }

    const statusEl = document.getElementById('tt-status');
    const st = effectivePlaceStatus(place);
    if (place.maintenance) {
        statusEl.textContent = 'На обслуживании';
        statusEl.className = 'tt-status-maint';
    } else if (st === 'partial') {
        statusEl.textContent = place.partial_occupancy
            ? `Частично (${place.partial_occupancy.occupied}/${place.partial_occupancy.capacity})`
            : 'Частично занято';
        statusEl.className = 'tt-status-partial';
    } else if (st === 'occupied') {
        statusEl.textContent = place.occupied_until ? 'Занято до ' + place.occupied_until : 'Занято';
        statusEl.className = 'tt-status-occ';
    } else {
        statusEl.textContent = 'Свободно';
        statusEl.className = 'tt-status-free';
    }

    tt.classList.add('visible');
    positionTooltip(tt, mouseX, mouseY);
}

function positionTooltip(tt, x, y) {
    const vw = window.innerWidth, vh = window.innerHeight;
    let left = x + 16, top = y + 10;
    if (left + 260 > vw) left = x - 260;
    if (top + 200 > vh)  top = y - 160;
    tt.style.left = left + 'px';
    tt.style.top  = top  + 'px';
}

function hideTooltip() {
    const tt = document.getElementById('place-tooltip');
    if (tt) tt.classList.remove('visible');
}

// ================== ОТРИСОВКА КАРТЫ ==================
function placeFill(place) {
    const st = effectivePlaceStatus(place);
    if (st === 'maintenance') return STATUS_OVERLAY.maintenance.fill;
    if (isAmenityPlace(place)) return AMENITY_FILL;
    if (st === 'occupied') return STATUS_OVERLAY.occupied.fill;
    if (st === 'partial') return STATUS_OVERLAY.partial.fill;
    if (isDeskZoneSpace(place)) return DESK_ZONE_FILL;
    return KIND_FILL[place.kind] || '#e5e7eb';
}
function placeStroke(place) {
    const st = effectivePlaceStatus(place);
    if (st === 'maintenance') return STATUS_OVERLAY.maintenance.stroke;
    if (isAmenityPlace(place)) return AMENITY_STROKE;
    if (st === 'occupied') return STATUS_OVERLAY.occupied.stroke;
    if (st === 'partial') return STATUS_OVERLAY.partial.stroke;
    if (isDeskZoneSpace(place)) return DESK_ZONE_STROKE;
    return KIND_STROKE[place.kind] || '#6b7280';
}
function kindLabel(kind) {
    if (kind === 'space' || kind === 'room') return 'Помещение';
    return kind === 'room' ? 'Переговорная' : 'Стол';
}

function childCount(place) {
    if (place.children_count) return place.children_count;
    if (place.code && childCountBySpaceCode[place.code] != null) {
        return childCountBySpaceCode[place.code];
    }
    return desksInSpace(place).length;
}

function parsePlaceKinds(raw) {
    if (Array.isArray(raw)) return raw;
    if (!raw) return [];
    if (typeof raw === 'string') {
        try {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [parsed];
        } catch {
            return [raw];
        }
    }
    return [];
}

function bookingPlaceKind(place) {
    if (!place) return 'desk';
    if (place.kind === 'desk') return 'desk';
    if (place.is_meeting_room || place.category?.kind === 'room') return 'room';
    if (isSpaceContainer(place) && place.allows_desks !== false) return 'desk';
    return place.kind || 'desk';
}

function placeHasActiveTariffs(place) {
    const tariffs = tariffsForPlace(place);
    return tariffs.some(t => t.active !== false);
}

function zoneSeatCapacity(place) {
    if (place.zone_seat_capacity != null) return place.zone_seat_capacity;
    if (place.code && zoneSeatCapacityBySpaceCode[place.code] != null) {
        return zoneSeatCapacityBySpaceCode[place.code];
    }
    return desksInSpace(place).reduce((sum, d) => sum + (d.capacity || 1), 0);
}

/** Вместимость для отображения: у зоны – сумма мест, логика брони не меняется. */
function displayCapacity(place) {
    if (isSpaceContainer(place) && !place.is_meeting_room) {
        const seats = zoneSeatCapacity(place);
        if (seats > 0) return seats;
    }
    if (place.partial_occupancy && place.partial_occupancy.capacity > 1) {
        return place.partial_occupancy.capacity;
    }
    return place.capacity || 1;
}

function renderFloorPlan() {
    const layer = document.getElementById('places-layer');
    const svg = document.getElementById('floor-plan');
    if (!layer) return;
    layer.innerHTML = '';

    // В режиме помещения – фокус на его границах
    if (activeSpace && svg) {
        const pad = Math.max(48, Math.min(activeSpace.width, activeSpace.height) * 0.08);
        svg.setAttribute('viewBox',
            `${activeSpace.x - pad} ${activeSpace.y - pad} ${activeSpace.width + pad * 2} ${activeSpace.height + pad * 2}`);
    } else if (svg) {
        svg.setAttribute('viewBox', '0 0 2240 1344');
    }

    // Фон помещения в режиме приближения
    if (activeSpace) {
        const floor = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        floor.setAttribute('x', activeSpace.x);
        floor.setAttribute('y', activeSpace.y);
        floor.setAttribute('width', activeSpace.width);
        floor.setAttribute('height', activeSpace.height);
        floor.setAttribute('rx', 0);
        floor.setAttribute('fill', '#f8fafc');
        floor.setAttribute('stroke', 'none');
        layer.appendChild(floor);
    }

    // Стены (внутри помещения – только пересекающие границы)
    (wallsByFloor[currentFloor] || []).forEach(wall => {
        if (activeSpace) {
            const inSpace = wallIntersectsRect(wall, activeSpace);
            if (!inSpace) return;
        }
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', wall.x1); line.setAttribute('y1', wall.y1);
        line.setAttribute('x2', wall.x2); line.setAttribute('y2', wall.y2);
        line.setAttribute('stroke', wall.protected ? '#334155' : (activeSpace ? '#94a3b8' : '#64748b'));
        line.setAttribute('stroke-width', activeSpace ? (wall.protected ? 5 : 3) : (wall.protected ? 8 : 4));
        line.setAttribute('stroke-linecap', 'round');
        layer.appendChild(line);
    });

    // Двери – арки как в редакторе
    const wallsById = Object.fromEntries(
        (wallsByFloor[currentFloor] || []).map(w => [w.id, w])
    );
    (doorsByFloor[currentFloor] || []).forEach(door => {
        const wall = wallsById[door.wall_id];
        if (!wall) return;
        const dx = wall.x2 - wall.x1, dy = wall.y2 - wall.y1;
        const len = Math.hypot(dx, dy);
        if (len < 1) return;
        const ux = dx / len, uy = dy / len;
        const mx = wall.x1 + dx * door.position, my = wall.y1 + dy * door.position;
        const hw = (door.width || 50) / 2;
        const sx = mx - ux * hw, sy = my - uy * hw;
        const ex = mx + ux * hw, ey = my + uy * hw;

        // Проем (белый зазор)
        const gap = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        gap.setAttribute('x1', sx); gap.setAttribute('y1', sy);
        gap.setAttribute('x2', ex); gap.setAttribute('y2', ey);
        gap.setAttribute('stroke', '#f8fafc');
        gap.setAttribute('stroke-width', 12);
        gap.setAttribute('stroke-linecap', 'round');
        layer.appendChild(gap);
    });

    // Граница активного помещения
    if (activeSpace) {
        const border = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        border.setAttribute('x', activeSpace.x + 2);
        border.setAttribute('y', activeSpace.y + 2);
        border.setAttribute('width', activeSpace.width - 4);
        border.setAttribute('height', activeSpace.height - 4);
        border.setAttribute('rx', 0);
        border.setAttribute('fill', 'none');
        border.setAttribute('stroke', '#0ea5e9');
        border.setAttribute('stroke-width', 2);
        border.setAttribute('opacity', '0.85');
        border.setAttribute('pointer-events', 'none');
        layer.appendChild(border);
    }

    // Места: контейнеры рисуем первыми, столы поверх – чтобы в режиме обслуживания клик попадал в стол
    const viewPlaces = placesForCurrentView();
    const sortedPlaces = [...viewPlaces].sort((a, b) => {
        const aDesk = isDesk(a) ? 1 : 0;
        const bDesk = isDesk(b) ? 1 : 0;
        // Столы поверх зон — в режиме обслуживания можно выбрать и зону, и отдельный стол
        return aDesk - bDesk;
    });
    const fragment = document.createDocumentFragment();
    sortedPlaces.forEach(place => {
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        const st = effectivePlaceStatus(place);
        g.classList.add('place-zone', st);
        if (isSpaceContainer(place) && !activeSpace) g.classList.add('space-container');
        g.dataset.id = place.id;
        if (editMode && editSelectedPlace?.id === place.id) g.classList.add('selected-for-edit');

        const x = place.x, y = place.y;
        const noGapWithContainer = isDesk(place) && place.container_code;
        const w = noGapWithContainer ? Math.max(1, place.width - 2) : place.width;
        const h = noGapWithContainer ? Math.max(1, place.height - 2) : place.height;
        const rotation = place.rotation || 0;

        // Прямоугольник
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', x); rect.setAttribute('y', y);
        rect.setAttribute('width', w); rect.setAttribute('height', h);
        rect.setAttribute('rx', 0);
        rect.setAttribute('fill', placeFill(place));
        rect.setAttribute('stroke', placeStroke(place));
        rect.setAttribute('stroke-width', showDeskOnMap(place) ? 2 : 3);
        rect.style.fill = placeFill(place);
        rect.style.stroke = placeStroke(place);
        if (isAmenityPlace(place)) {
            rect.setAttribute('stroke-dasharray', '12 6');
            rect.setAttribute('stroke-width', 4);
        }
        if (rotation) {
            rect.setAttribute('transform', `rotate(${rotation} ${x + w/2} ${y + h/2})`);
        }
        g.appendChild(rect);

        const nameText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        nameText.setAttribute('x', x + w / 2);
        nameText.setAttribute('y', y + h / 2 + (showDeskOnMap(place) ? 0 : -4));
        nameText.setAttribute('text-anchor', 'middle');
        nameText.setAttribute('dominant-baseline', 'middle');
        nameText.setAttribute('fill', isAmenityPlace(place) ? '#581c87' : (showDeskOnMap(place) ? '#14532d' : '#1e293b'));
        nameText.setAttribute('font-size', showDeskOnMap(place)
            ? Math.min(12, Math.max(9, Math.min(w, h) / 5))
            : Math.min(13, Math.max(9, w / 10)));
        nameText.setAttribute('font-weight', '700');
        nameText.setAttribute('pointer-events', 'none');
        nameText.setAttribute('style', '-webkit-user-select:none;user-select:none;');
        nameText.textContent = isSpaceContainer(place) ? placeDisplayName(place) : deskDisplayLabel(place, w);
        g.appendChild(nameText);

        // Для одиночных столов capText не добавляем – вся информация видна в тултипе
        if (!showDeskOnMap(place)) {
            const capText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            capText.setAttribute('pointer-events', 'none');
            capText.setAttribute('x', x + w / 2);
            capText.setAttribute('y', y + h / 2 + 10);
            capText.setAttribute('text-anchor', 'middle');
            capText.setAttribute('dominant-baseline', 'middle');
            capText.setAttribute('font-size', Math.min(10, Math.max(8, w / 12)));

            if (place.partial_occupancy) {
                capText.setAttribute('fill', st === 'partial' ? '#d97706' : '#dc2626');
                capText.setAttribute('font-weight', '600');
                capText.textContent = `${place.partial_occupancy.occupied}/${place.partial_occupancy.capacity} занято`;
            } else if (isAmenityPlace(place)) {
                capText.setAttribute('fill', '#7e22ce');
                capText.textContent = 'служебная зона';
            } else if (place.is_meeting_room) {
                capText.setAttribute('fill', '#475569');
                capText.textContent = `${displayCapacity(place)} мест · забронировать`;
            } else {
                const seats = zoneSeatCapacity(place);
                const cnt = childCount(place);
                capText.setAttribute('fill', '#475569');
                capText.textContent = seats
                    ? `${seats} мест · войти`
                    : (cnt ? `${cnt} столов · войти` : 'пусто · войти');
            }
            g.appendChild(capText);
        }

        fragment.appendChild(g);
    });
    layer.appendChild(fragment);
}

function setupMapEventDelegation() {
    const layer = document.getElementById('places-layer');
    if (!layer || layer.dataset.delegated === '1') return;
    layer.dataset.delegated = '1';

    layer.addEventListener('mousemove', e => {
        const g = e.target.closest('.place-zone');
        if (!g) {
            hideTooltip();
            return;
        }
        const place = placesByIdMap.get(parseInt(g.dataset.id, 10));
        if (place) showTooltip(place, e.clientX, e.clientY);
    });
    layer.addEventListener('mouseleave', hideTooltip);
    layer.addEventListener('click', e => {
        const g = e.target.closest('.place-zone');
        if (!g) return;
        e.stopPropagation();
        const place = placesByIdMap.get(parseInt(g.dataset.id, 10));
        if (!place) return;
        if (editMode) selectPlaceForEdit(place);
        else handlePlaceClick(place);
    });
}

function wallIntersectsRect(wall, rect) {
    const minX = Math.min(wall.x1, wall.x2), maxX = Math.max(wall.x1, wall.x2);
    const minY = Math.min(wall.y1, wall.y2), maxY = Math.max(wall.y1, wall.y2);
    return !(maxX < rect.x || minX > rect.x + rect.width || maxY < rect.y || minY > rect.y + rect.height);
}

function handlePlaceClick(place) {
    if (editMode) {
        selectPlaceForEdit(place);
        return;
    }
    if (isAmenityPlace(place)) {
        showAlert(place.name + ': служебная зона, бронирование недоступно', 'info');
        return;
    }
    // Одиночный стол в коридоре – сразу бронь
    if (!activeSpace && isOrphanDesk(place)) {
        selectPlaceForBooking(place);
        return;
    }
    // Переговорная без столов внутри – бронь комнаты целиком
    if (!activeSpace && isSpaceContainer(place) && place.is_meeting_room) {
        const children = desksInSpace(place);
        if (!children.length) {
            selectPlaceForBooking(place);
            return;
        }
    }
    // Рабочая зона или переговорная со столами – войти и выбрать место
    if (!activeSpace && isSpaceContainer(place)) {
        enterSpaceView(place);
        return;
    }
    // Внутри помещения – клик по столу = бронирование (только рабочие зоны)
    if (activeSpace && isDesk(place)) {
        selectPlaceForBooking(place);
        return;
    }
}

function deskDisplayLabel(place, w) {
    const name = placeDisplayName(place);
    const maxLen = Math.max(6, Math.floor(w / 6));
    if (name.length <= maxLen) return name;
    return name.slice(0, Math.max(1, maxLen - 1)) + '…';
}

function updateSpaceViewBar() {
    const bar = document.getElementById('space-view-bar');
    if (!bar) return;
    const show = Boolean(activeSpace) && currentUserView === 'map';
    bar.style.display = show ? 'flex' : 'none';
}

function enterSpaceView(space) {
    activeSpace = space;
    invalidateViewCache();
    selectedPlace = null;
    document.getElementById('booking-form').style.display = 'none';
    document.querySelector('.floor-plan-container')?.classList.add('space-zoom-active');
    spaceEntryZoomLevel = zoomLevel;
    const bar = document.getElementById('space-view-bar');
    if (bar) {
        document.getElementById('space-view-title').textContent = space.name;
    }
    updateSpaceViewBar();
    const children = desksInSpace(space);
    if (!children.length) {
        showAlert('В этом помещении пока нет столов. Обратитесь к администратору.', 'info');
    }
    renderFloorPlan();
    updateManagerStatusList();
}

function exitSpaceView() {
    activeSpace = null;
    invalidateViewCache();
    spaceEntryZoomLevel = null;
    document.querySelector('.floor-plan-container')?.classList.remove('space-zoom-active');
    updateSpaceViewBar();
    renderFloorPlan();
    updateManagerStatusList();
}

function bookWholeSpace() {
    if (!activeSpace) return;
    selectPlaceForBooking(activeSpace);
}

// ================== РЕЖИМ РЕДАКТИРОВАНИЯ ==================
function updateEditSelectionHighlight() {
    document.querySelectorAll('#places-layer .place-zone').forEach(g => {
        const id = parseInt(g.dataset.id, 10);
        g.classList.toggle('selected-for-edit', editMode && editSelectedPlace?.id === id);
    });
}

function scrollToMaintenancePanel() {
    const target = document.getElementById('maintenance-toggle-row')
        || document.getElementById('maintenance-panel');
    if (!target) return;
    requestAnimationFrame(() => {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
}

function updateMaintenanceInheritedHint(place) {
    const hint = document.getElementById('maintenance-inherited-hint');
    if (!hint) return;
    const ownMaint = place.own_maintenance ?? place.maintenance;
    if (place.maintenance && !ownMaint) {
        hint.style.display = 'block';
        hint.textContent = 'Серым отображается из‑за обслуживания зоны. Переключатель ниже — только для этого места.';
    } else {
        hint.style.display = 'none';
        hint.textContent = '';
    }
}

function selectPlaceForEdit(place) {
    if (!place?.id) {
        showAlert('Для этого объекта нельзя включить обслуживание (нет записи в базе)', 'warning');
        return;
    }
    editSelectedPlace = place;
    document.getElementById('edit-place-name').textContent = placeLabelWithCode(place);
    const ownMaint = place.own_maintenance ?? place.maintenance;
    document.getElementById('maintenance-toggle-input').checked = !!ownMaint;
    document.getElementById('maintenance-panel').classList.add('active');
    updateMaintenanceInheritedHint(place);
    updateEditSelectionHighlight();
    updateManagerStatusList();
    scrollToMaintenancePanel();
}

function toggleEditMode() {
    editMode = !editMode;
    invalidateViewCache();
    document.body.classList.toggle('edit-mode', editMode);
    document.getElementById('edit-mode-bar').classList.toggle('active', editMode);
    document.getElementById('toggle-edit-mode')?.classList.toggle('active', editMode);
    if (!editMode) {
        editSelectedPlace = null;
        document.body.classList.remove('edit-mode');
        document.getElementById('maintenance-panel').classList.remove('active');
    }
    renderFloorPlan();
    updateManagerStatusList(); // Обновляем список для отображения выделения в режиме редактирования
}

async function applyMaintenance() {
    if (!editSelectedPlace?.id) {
        showAlert('Сначала выберите место на карте', 'warning');
        document.getElementById('maintenance-toggle-input').checked = false;
        return;
    }

    const placeId = editSelectedPlace.id;
    const toggle = document.getElementById('maintenance-toggle-input');
    const maintenance = !!toggle?.checked;

    try {
        const r = await fetch(`/api/admin/places/${placeId}/maintenance`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ maintenance }),
        });
        let d = null;
        try {
            d = await r.json();
        } catch {
            d = null;
        }
        if (!r.ok || !d?.success) {
            if (toggle) toggle.checked = !maintenance;
            showAlert(d?.error || `Ошибка сервера (${r.status})`, 'error');
            return;
        }
        showAlert(
            d.message || (maintenance ? 'Место переведено на обслуживание' : 'Обслуживание снято'),
            d.inherited_from_parent ? 'warning' : 'success',
        );
        await loadPlaces();
        if (editMode) {
            const updated = places.find(p => p.id === placeId);
            if (updated) selectPlaceForEdit(updated);
        }
    } catch {
        if (toggle) toggle.checked = !maintenance;
        showAlert('Ошибка обновления', 'error');
    }
}

// ================== ТАРИФЫ ==================
let categoryTariffs = {};
let currentPlaceTariffs = [];

function tariffsForPlace(place) {
    const catId = place?.category?.id;
    if (catId && categoryTariffs[catId]) return categoryTariffs[catId];
    return place?.tariffs || place?.category?.tariffs || [];
}

const TARIFF_LABELS = {
    hourly: 'Часовой (почасовая)',
    weekly: 'Недельный (фикс)',
    monthly: 'Месячный (фикс)'
};

const TARIFF_DESCRIPTIONS = {
    hourly: 'Оплата за каждый час работы',
    weekly: 'Фиксированная цена на неделю (7 дней)',
    monthly: 'Фиксированная цена на месяц (30 дней)'
};

const TARIFF_PERIOD_DAYS = { weekly: 7, monthly: 30 };

function formatRuShortDate(iso) {
    if (!iso) return '';
    const [y, m, d] = iso.split('-');
    return `${d}.${m}.${y}`;
}

function periodEndDateIso(startIso, tariffType) {
    const days = TARIFF_PERIOD_DAYS[tariffType];
    if (!startIso || !days) return startIso || '';
    const dt = new Date(startIso + 'T12:00:00');
    dt.setDate(dt.getDate() + days - 1);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, '0');
    const d = String(dt.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function formatBookingPeriod(startIso, tariffType) {
    if (!startIso) return '-';
    if (tariffType !== 'weekly' && tariffType !== 'monthly') {
        return formatRuShortDate(startIso);
    }
    const end = periodEndDateIso(startIso, tariffType);
    return `${formatRuShortDate(startIso)} - ${formatRuShortDate(end)}`;
}

function updateBookingPeriodDisplay() {
    const tariffType = document.getElementById('tariff-type')?.value || 'hourly';
    const start = getBookingDate();
    const isFixed = tariffType === 'weekly' || tariffType === 'monthly';
    const labelEl = document.getElementById('booking-date-label');
    const hintEl = document.getElementById('booking-period-hint');
    const periodRow = document.getElementById('booking-period-row');
    const periodDisplay = document.getElementById('booking-period-display');

    if (labelEl) labelEl.textContent = isFixed ? 'Дата начала' : 'Дата бронирования';
    const range = formatBookingPeriod(start, tariffType);
    if (hintEl) {
        hintEl.style.display = isFixed && start ? 'block' : 'none';
        hintEl.textContent = isFixed && start ? `Срок: ${range}` : '';
    }
    if (periodRow) periodRow.style.display = isFixed ? 'flex' : 'none';
    if (periodDisplay) periodDisplay.textContent = isFixed ? range : '';
}

const TARIFF_ORDER = { hourly: 0, weekly: 1, monthly: 2 };

function sortTariffsByDefault(tariffs) {
    return [...tariffs].sort((a, b) => {
        const orderA = TARIFF_ORDER[a.tariff_type] ?? 9;
        const orderB = TARIFF_ORDER[b.tariff_type] ?? 9;
        return orderA - orderB;
    });
}

function updateTariffSelector() {
    const select = document.getElementById('tariff-type');
    if (!select || select.tagName !== 'SELECT') return;

    select.innerHTML = '';
    const availableTariffs = sortTariffsByDefault(
        (currentPlaceTariffs || []).filter(t => t.active)
    );

    if (availableTariffs.length === 0) {
        select.innerHTML = '<option value="">Нет доступных тарифов</option>';
        return;
    }

    availableTariffs.forEach(t => {
        const option = document.createElement('option');
        option.value = t.tariff_type;
        const priceHint = t.price ? ` – ${Math.round(t.price).toLocaleString('ru-RU')} ₽` : '';
        option.textContent = (TARIFF_LABELS[t.tariff_type] || t.tariff_type) + priceHint;
        select.appendChild(option);
    });
}

function onTariffChange() {
    const tariffType = document.getElementById('tariff-type')?.value;
    if (!tariffType) return;

    const descEl = document.getElementById('tariff-description');
    const displayEl = document.getElementById('tariff-type-display');
    if (descEl) descEl.textContent = TARIFF_DESCRIPTIONS[tariffType] || '';
    if (displayEl) {
        displayEl.textContent = {
            hourly: 'Часовой',
            weekly: 'Недельный',
            monthly: 'Месячный'
        }[tariffType] || tariffType;
    }

    const timeSection = document.getElementById('timegrid-container');
    const durationRow = document.getElementById('duration-row');
    const timePickerRow = document.getElementById('time-picker-row');
    const fixedHint = document.getElementById('fixed-tariff-hint');
    const hourlyHint = document.getElementById('hourly-hint');
    const hideTimeline = typeof isMobileViewport === 'function' && isMobileViewport();
    const isHourly = tariffType === 'hourly';

    if (timeSection) timeSection.style.display = (isHourly && !hideTimeline) ? 'block' : 'none';
    if (durationRow) durationRow.style.display = isHourly ? 'flex' : 'none';
    if (timePickerRow) timePickerRow.style.display = isHourly ? 'block' : 'none';
    if (fixedHint) fixedHint.style.display = isHourly ? 'none' : 'block';
    if (hourlyHint) hourlyHint.style.display = isHourly ? 'block' : 'none';

    if (!isHourly && window.currentSchedule) {
        const [openH, openM] = window.currentSchedule.open.split(':');
        const [closeH, closeM] = window.currentSchedule.close.split(':');
        const sh = document.getElementById('start-hour');
        const sm = document.getElementById('start-min');
        const eh = document.getElementById('end-hour');
        const em = document.getElementById('end-min');
        if (sh) sh.value = openH;
        if (sm) sm.value = openM;
        if (eh) eh.value = closeH;
        if (em) em.value = closeM;
    }

    if (isHourly && selectedPlace) {
        const date = document.getElementById('booking-date')?.value;
        if (date && typeof loadTimegrid === 'function') {
            loadTimegrid(selectedPlace.id, date);
        }
    }

    updateBookingPeriodDisplay();
    updatePeopleCountForSubscription();
    schedulePriceDisplayUpdate();
}

function initTariffsForPlace(place) {
    currentPlaceTariffs = tariffsForPlace(place);
    updateTariffSelector();

    const availableTariffs = sortTariffsByDefault(
        currentPlaceTariffs.filter(t => t.active !== false)
    );
    const bookBtn = document.getElementById('book-btn');
    const noTariffHint = document.getElementById('no-tariff-hint');

    if (availableTariffs.length) {
        const defaultTariff = availableTariffs.find(t => t.tariff_type === 'hourly') || availableTariffs[0];
        document.getElementById('tariff-type').value = defaultTariff.tariff_type;
        if (bookBtn) {
            bookBtn.disabled = false;
            bookBtn.title = '';
        }
        if (noTariffHint) noTariffHint.style.display = 'none';
    } else {
        if (bookBtn) {
            bookBtn.disabled = true;
            bookBtn.title = 'Нет тарифов, бронирование недоступно';
        }
        if (noTariffHint) noTariffHint.style.display = 'block';
    }
    onTariffChange();
}

// ================== БРОНИРОВАНИЕ ==================
let clientsCache = null;
async function loadClientUsers() {
    if (typeof IS_MANAGER === 'undefined' || !IS_MANAGER) return;
    if (clientsCache) return;
    try {
        const r = await fetch('/api/users?role=client');
        const d = await r.json();
        if (d.success) {
            clientsCache = d.users;
            const select = document.getElementById('booking-user-id');
            if (select) {
                select.innerHTML = '<option value="">Я</option>';
                d.users.forEach(u => {
                    const opt = document.createElement('option');
                    opt.value = u.id;
                    opt.textContent = `${u.username} (${u.phone || u.email})`;
                    select.appendChild(opt);
                });
            }
        }
    } catch (e) { console.error('Ошибка загрузки клиентов', e); }
}

async function selectPlaceForBooking(place) {
    if (place.maintenance) {
        showAlert('Место на обслуживании, бронирование недоступно', 'warning');
        return;
    }
    if (!placeHasActiveTariffs(place)) {
        showAlert('Для этого места не настроены тарифы, бронирование невозможно. Обратитесь к администратору.', 'warning');
        return;
    }
    selectedPlace = place;
    document.getElementById('selected-place-name').textContent = placeDisplayName(place);
    const metaEl = document.getElementById('selected-place-meta');
    if (metaEl) {
        if (place.location_path) {
            metaEl.textContent = place.location_path;
        } else {
            const floorLabel = place.floor_name || ('Этаж ' + (place.floor || 1));
            const locLabel = place.location_display
                || (place.parent_name
                    ? `${place.parent_name} (${place.container_code || ''})`
                    : (place.location_name
                        ? `${place.location_name} (${place.location_code || ''})`
                        : (place.location_code || '')));
            metaEl.textContent = `${floorLabel}${locLabel ? ' · ' + locLabel : ''}`;
        }
    }
    document.getElementById('booking-form').style.display = 'block';

    // Загружаем список клиентов для менеджера
    loadClientUsers();
    await refreshBookingSubscriptions(getBookingTargetUserId());

    updatePeopleCountForSubscription();

    if ((place.status === 'occupied' || place.status === 'partial') && place.occupied_until) {
        document.getElementById('occupied-warning').style.display = 'flex';
        document.getElementById('current-occupation').style.display = 'flex';
        document.getElementById('occupied-until').textContent = place.occupied_until;
    } else {
        document.getElementById('occupied-warning').style.display = 'none';
        document.getElementById('current-occupation').style.display = 'none';
    }

    initTariffsForPlace(place);

    const tariffType = document.getElementById('tariff-type')?.value || 'hourly';
    const payCb = document.getElementById('pay-without-subscription');
    if (payCb) payCb.checked = false;
    schedulePriceDisplayUpdate();
    const timegridContainer = document.getElementById('timegrid-container');
    if (timegridContainer && tariffType === 'hourly' && !(typeof isMobileViewport === 'function' && isMobileViewport())) {
        if (typeof updateTimegridCapacity === 'function') {
            updateTimegridCapacity({ zone_capacity: place.zone_seat_capacity, capacity: displayCapacity(place) });
        } else {
            document.getElementById('timegrid-capacity').textContent = `Вместимость: ${displayCapacity(place)}`;
        }
    }
    selectedDurationSlots = 4;
    if (typeof updateDurationDisplay === 'function') updateDurationDisplay();

    document.getElementById('booking-form').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function selectPlaceByCode(placeCode) {
    const place = places.find(p => p.code === placeCode);
    if (place) handlePlaceClick(place);
}

function applyInitialMapFocus(params) {
    const placeCode = params.get('place');
    if (!placeCode) return;
    const place = places.find(p => p.code === placeCode);
    if (!place) {
        showAlert('Место из обращения не найдено на карте', 'warning');
        return;
    }
    if (Number(place.floor || 1) !== Number(currentFloor)) {
        currentFloor = Number(place.floor || 1);
        renderFloorToggles();
    }
    const parent = place.container_code
        ? places.find(p => p.code === place.container_code)
        : null;
    if (parent && isSpaceContainer(parent)) {
        enterSpaceView(parent);
    } else {
        renderFloorPlan();
    }
    selectPlaceByCode(place.code);
    setTimeout(() => {
        document.getElementById('booking-form')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);
}

function filterPastHours(dateVal) {
    const openTime = window.currentSchedule?.open;
    const closeTime = window.currentSchedule?.close;
    if (typeof rebuildTimeSelects === 'function' && openTime && closeTime) {
        rebuildTimeSelects(openTime, closeTime);
        return;
    }
    filterPastMinuteOptions();
}

let priceDisplayTimer = null;
let priceFetchGeneration = 0;

function schedulePriceDisplayUpdate() {
    clearTimeout(priceDisplayTimer);
    priceDisplayTimer = setTimeout(() => updatePriceDisplay(), 300);
}

function shouldUseSubscription(subscription, tariffType) {
    if (!subscription || tariffType !== 'hourly') return false;
    const cb = document.getElementById('pay-without-subscription');
    return !(cb && cb.checked);
}

function updateSubscriptionPayOption(subscription, tariffType) {
    const row = document.getElementById('pay-without-subscription-row');
    if (!row) return;
    const show = !!(subscription && tariffType === 'hourly');
    row.style.display = show ? 'flex' : 'none';
    if (!show) {
        const cb = document.getElementById('pay-without-subscription');
        if (cb) cb.checked = false;
    }
}

function updatePeopleCountForSubscription() {
    if (!selectedPlace) return;

    const tariffType = document.getElementById('tariff-type')?.value || 'hourly';
    const subscription = getApplicableSubscriptionForTariff(bookingPlaceKind(selectedPlace), tariffType);
    const useSub = shouldUseSubscription(subscription, tariffType);

    const isMeeting = selectedPlace.is_meeting_room
        || (isSpaceContainer(selectedPlace) && selectedPlace.category?.kind === 'room');
    const peopleRow = document.getElementById('people-count-row');
    const peopleSummary = document.getElementById('people-summary-row');
    const select = document.getElementById('people-count');

    if (isMeeting) {
        if (peopleRow) peopleRow.style.display = 'none';
        if (peopleSummary) peopleSummary.style.display = 'none';
        return;
    }

    if (useSub) {
        if (peopleRow) peopleRow.style.display = 'none';
        if (peopleSummary) peopleSummary.style.display = 'none';
        if (select) select.value = '1';
        return;
    }

    if (selectedPlace.capacity > 1 && selectedPlace.kind === 'desk') {
        if (peopleRow) peopleRow.style.display = 'flex';
        if (peopleSummary) peopleSummary.style.display = 'flex';
        if (select) {
            Array.from(select.options).forEach(opt => {
                opt.disabled = parseInt(opt.value, 10) > selectedPlace.capacity;
            });
            if (parseInt(select.value, 10) > selectedPlace.capacity) select.value = '1';
        }
    } else {
        if (peopleRow) peopleRow.style.display = 'none';
        if (peopleSummary) peopleSummary.style.display = 'none';
        if (select) select.value = '1';
    }
}

async function updatePriceDisplay() {
    if (!selectedPlace) return;

    const totalEl = document.getElementById('total-price');
    if (!totalEl) return;

    const tariffType = document.getElementById('tariff-type')?.value || 'hourly';
    const startTime = getStartTime();
    const endTime = getEndTime();
    const [sh, sm] = startTime.split(':').map(Number);
    const [eh, em] = endTime.split(':').map(Number);
    const diffMins = (eh * 60 + em) - (sh * 60 + sm);

    let peopleCount = 1;
    const peopleSelect = document.getElementById('people-count');
    if (peopleSelect && selectedPlace.capacity > 1) {
        peopleCount = parseInt(peopleSelect.value, 10) || 1;
    }

    const subscription = getApplicableSubscriptionForTariff(bookingPlaceKind(selectedPlace), tariffType);
    updateSubscriptionPayOption(subscription, tariffType);
    updatePeopleCountForSubscription();
    if (shouldUseSubscription(subscription, tariffType)) {
        const remaining = subscription.hours_limit === null ? '∞' : subscription.hours_remaining;
        totalEl.textContent = `По абонементу (ост. ${remaining} ч)`;
        return;
    }

    if (tariffType === 'hourly' && diffMins < 30) {
        totalEl.textContent = '-';
        return;
    }

    if (typeof fetchBookingPrice !== 'function') {
        totalEl.textContent = '-';
        return;
    }

    try {
        const fetchGen = ++priceFetchGeneration;
        const payWithoutSub = document.getElementById('pay-without-subscription')?.checked;
        const d = await fetchBookingPrice(
            selectedPlace.id, startTime, endTime, peopleCount, tariffType,
            { noSubscription: !!payWithoutSub },
        );
        if (fetchGen !== priceFetchGeneration) return;
        if (d.success) {
            totalEl.textContent = formatRubles(d.total_price);
        } else {
            totalEl.textContent = '-';
        }
    } catch {
        totalEl.textContent = '-';
    }
}

async function checkAvailability() {
    if (!selectedPlace) return;
    const bookingDate = getBookingDate();
    const startTime   = getStartTime();
    const endTime     = getEndTime();

    if (!bookingDate) { showAlert('Укажите дату', 'warning'); return; }

    const now = getNow();
    if (bookingDate < now.toISOString().split('T')[0]) {
        showAlert('Нельзя бронировать на прошедшую дату', 'warning');
        return;
    }

    const [sh, sm] = startTime.split(':').map(Number);
    const [eh, em] = endTime.split(':').map(Number);
    if (bookingDate === now.toISOString().split('T')[0] && (sh * 60 + sm) < now.getHours() * 60 + now.getMinutes()) {
        showAlert('Нельзя бронировать на прошедшее время', 'warning');
        return;
    }
    if ((eh * 60 + em) - (sh * 60 + sm) < 30) {
        showAlert('Минимальная продолжительность: 30 минут', 'warning'); return;
    }

    let peopleCount = 1;
    const isMeetingCheck = selectedPlace.is_meeting_room
        || (isSpaceContainer(selectedPlace) && selectedPlace.category?.kind === 'room');
    if (isMeetingCheck) {
        peopleCount = selectedPlace.capacity || 1;
    } else {
        const peopleSelect = document.getElementById('people-count');
        if (peopleSelect && selectedPlace.capacity > 1) {
            peopleCount = parseInt(peopleSelect.value) || 1;
        }
    }

    // Проверяем доступность через API
    try {
        const d = await checkBooking(selectedPlace.id, bookingDate, startTime, endTime, peopleCount, tariffType);
        if (d.success && d.is_available) {
            showAlert(d.message + '<br>Стоимость: ' + formatRubles(d.total_price), 'success');
        } else {
            showAlert(d.message || d.error || 'Время недоступно', 'error');
        }
    } catch {
        showAlert('Ошибка проверки доступности', 'error');
    }
}

function isValid15MinTime(h, m) {
    return m % 15 === 0;
}

// Универсальный обработчик бронирования (использует новый API)
async function handleBooking() {
    if (!selectedPlace) return;
    const bookingDate = getBookingDate();
    let startTime = getStartTime();
    let endTime = getEndTime();
    const tariffType = document.getElementById('tariff-type')?.value || 'hourly';

    if (!bookingDate) { showAlert('Укажите дату', 'warning'); return; }
    if (!tariffType) { showAlert('Для этого места нет доступных тарифов, бронирование невозможно', 'warning'); return; }

    if (tariffType !== 'hourly' && window.currentSchedule) {
        const [openH, openM] = window.currentSchedule.open.split(':');
        const [closeH, closeM] = window.currentSchedule.close.split(':');
        startTime = `${openH}:${openM}`;
        endTime = `${closeH}:${closeM}`;
    }

    const [sh, sm] = startTime.split(':').map(Number);
    const [eh, em] = endTime.split(':').map(Number);

    if (tariffType === 'hourly') {
        if (!isValid15MinTime(sh, sm) || !isValid15MinTime(eh, em)) {
            showAlert('Время должно быть кратно 15 минутам', 'warning');
            return;
        }
        if ((eh * 60 + em) - (sh * 60 + sm) < 30) {
            showAlert('Минимальная продолжительность: 30 минут', 'warning');
            return;
        }
    }

    let peopleCount = 1;
    const isMeetingBook = selectedPlace.is_meeting_room
        || (isSpaceContainer(selectedPlace) && selectedPlace.category?.kind === 'room');
    const subscription = getApplicableSubscriptionForTariff(bookingPlaceKind(selectedPlace), tariffType);
    const useSub = shouldUseSubscription(subscription, tariffType);

    if (isMeetingBook) {
        peopleCount = selectedPlace.capacity || 1;
    } else if (!useSub) {
        const peopleSelect = document.getElementById('people-count');
        if (peopleSelect && selectedPlace.capacity > 1) {
            peopleCount = parseInt(peopleSelect.value, 10) || 1;
        }
    }

    const now = getNow();
    if (bookingDate < now.toISOString().split('T')[0]) {
        showAlert('Нельзя бронировать на прошедшую дату', 'warning');
        return;
    }
    if (tariffType === 'hourly' && bookingDate === now.toISOString().split('T')[0]) {
        const [sh, sm] = startTime.split(':').map(Number);
        const startMins = sh * 60 + sm;
        const nowMins = now.getHours() * 60 + now.getMinutes();
        if (startMins < nowMins) {
            showAlert('Нельзя бронировать на прошедшее время', 'warning');
            return;
        }
    }

    const bookBtn = document.getElementById('book-btn');
    const originalText = bookBtn?.innerHTML;
    if (bookBtn) {
        bookBtn.disabled = true;
        bookBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Создание...';
    }

    try {
        const targetUserId = getBookingTargetUserId();
        let d;

        if (useSub) {
            d = await bookWithSubscription(subscription.id, selectedPlace.id, bookingDate, startTime, endTime, targetUserId);
        } else {
            d = await createBookingModule(
                selectedPlace.id, bookingDate, startTime, endTime, peopleCount, tariffType, targetUserId,
                subscription ? false : undefined,
            );
        }

        if (d.success) {
            const priceShown = useSub ? 0 : (d.total_price || 0);
            showBookingSuccess(placeDisplayName(selectedPlace), bookingDate, startTime, endTime, priceShown, tariffType);
            cancelBookingForm();
            loadPlaces();
            await refreshBookingSubscriptions(getBookingTargetUserId());
        } else {
            showAlert(d.error || d.message || 'Ошибка создания бронирования', 'error');
        }
    } catch (e) {
        showAlert('Ошибка: ' + e.message, 'error');
    } finally {
        if (bookBtn) {
            bookBtn.disabled = false;
            bookBtn.innerHTML = originalText;
        }
    }
}

function cancelBookingForm() {
    selectedPlace = null;
    currentPlaceTariffs = [];
    window.currentSchedule = null;
    if (typeof resetBookingSelection === 'function') resetBookingSelection();
    if (typeof hideScheduleStatus === 'function') hideScheduleStatus();
    const payCb = document.getElementById('pay-without-subscription');
    if (payCb) payCb.checked = false;
    const payRow = document.getElementById('pay-without-subscription-row');
    if (payRow) payRow.style.display = 'none';
    document.getElementById('booking-form').style.display = 'none';
    const timegridContainer = document.getElementById('timegrid-container');
    if (timegridContainer) timegridContainer.style.display = 'none';
    const hoursInfo = document.getElementById('schedule-hours-info');
    if (hoursInfo) hoursInfo.style.display = 'none';
}


async function loadPlaces() {
    try {
        await loadFloors();
        const r = await fetch('/api/places');
        const data = await r.json();
        places = data.places || [];
        categoryTariffs = data.category_tariffs || {};
        window.allPlaces = places;
        wallsData = data.walls || [];
        doorsData = data.doors || [];
        buildPlaceIndexes();
        renderFloorPlan();
        if (currentUserView === 'list' && typeof renderPlacesList === 'function') {
            renderPlacesList();
        } else if (IS_STAFF) {
            updateManagerStatusList();
        }
    } catch {
        showAlert('Ошибка загрузки данных карты', 'error');
    }
}

function getBookingTargetUserId() {
    const userSelect = document.getElementById('booking-user-id');
    if (IS_STAFF && userSelect && userSelect.value) {
        return userSelect.value;
    }
    return null;
}

async function loadUserSubscriptions() {
    try {
        const r = await fetch('/api/my/subscriptions');
        const d = await r.json();
        if (d.success) {
            userSubscriptions = d.subscriptions || [];
        }
    } catch {
        userSubscriptions = [];
    }
}

async function refreshBookingSubscriptions(targetUserId) {
    if (targetUserId) {
        try {
            const r = await fetch(`/api/staff/users/${targetUserId}/subscriptions`);
            const d = await r.json();
            userSubscriptions = d.success ? (d.subscriptions || []) : [];
        } catch {
            userSubscriptions = [];
        }
        return;
    }
    await loadUserSubscriptions();
}

// Проверить, есть ли подходящий абонемент для места данного типа
function getApplicableSubscription(placeKind) {
    const now = new Date().toISOString().split('T')[0];
    return userSubscriptions.find(sub => {
        // Проверяем дату
        if (sub.start_date > now || sub.end_date < now) return false;
        // Проверяем тип места
        const kinds = parsePlaceKinds(sub.place_kinds);
        return kinds.includes(placeKind);
    });
}

/** Абонемент с лимитом часов применяется только к почасовому тарифу. */
function getApplicableSubscriptionForTariff(placeKind, tariffType) {
    if (tariffType !== 'hourly') return null;
    return getApplicableSubscription(placeKind);
}

// ================== ОБРАБОТЧИКИ ==================
function setupEventListeners() {
    document.getElementById('booking-date')?.addEventListener('change', function () {
        onBookingDateChange();
    });
    document.getElementById('book-btn')?.addEventListener('click', handleBooking);
    document.getElementById('cancel-btn')?.addEventListener('click', cancelBookingForm);
    document.getElementById('booking-user-id')?.addEventListener('change', async function () {
        await refreshBookingSubscriptions(this.value || null);
        schedulePriceDisplayUpdate();
    });
}

// ================== ЭТАЖИ ==================
let availableFloors = [{ number: 1, label: 'Этаж 1' }];

async function loadFloors() {
    try {
        const r = await fetch('/api/floors');
        const d = await r.json();
        if (d.success && Array.isArray(d.floors) && d.floors.length) {
            availableFloors = d.floors;
            const nums = availableFloors.map(f => f.number);
            if (!nums.includes(currentFloor)) {
                currentFloor = availableFloors[0].number;
            }
        }
    } catch (e) {
        console.warn('Не удалось загрузить этажи', e);
    }
    renderFloorToggles();
}

function renderFloorToggles() {
    const mapToggle = document.getElementById('floor-map-toggle');
    const listToggle = document.getElementById('list-floor-toggle');
    const buttonsHtml = availableFloors.map(f => {
        const label = f.label || f.name || `Этаж ${f.number}`;
        const active = Number(f.number) === Number(currentFloor) ? 'active' : '';
        return `<button type="button" id="floor-map-btn-${f.number}" class="${active}" onclick="setMapFloor(${f.number})">${label}</button>`;
    }).join('');
    if (mapToggle) mapToggle.innerHTML = buttonsHtml;
    if (listToggle) listToggle.innerHTML = buttonsHtml;
}

function setMapFloor(floor) {
    currentFloor = floor;
    if (typeof listActiveZoneCode !== 'undefined') {
        listActiveZoneCode = null;
    }
    activeSpace = null;
    invalidateViewCache();
    updateSpaceViewBar();
    document.querySelectorAll('[id^="floor-map-btn-"]').forEach(b => b.classList.remove('active'));
    document.getElementById('floor-map-btn-' + floor)?.classList.add('active');
    renderFloorToggles();
    renderFloorPlan();
    if (currentUserView === 'list' && typeof renderPlacesList === 'function') {
        renderPlacesList();
    } else if (IS_STAFF) {
        updateManagerStatusList();
    }
}

// ================== ZOOM ==================
function clampZoomLevel(level) {
    return Math.min(Math.max(level, DEFAULT_MAP_ZOOM), 3);
}

function zoomIn() {
    zoomLevel = clampZoomLevel(zoomLevel * 1.25);
    applyZoom();
}

function zoomOut() {
    zoomLevel = clampZoomLevel(zoomLevel / 1.25);
    applyZoom();
}

function zoomReset() {
    zoomLevel = (activeSpace && spaceEntryZoomLevel != null) ? spaceEntryZoomLevel : DEFAULT_MAP_ZOOM;
    applyZoom();
}

function applyZoom() {
    const svg = document.getElementById('floor-plan');
    if (!svg) return;
    zoomLevel = clampZoomLevel(zoomLevel);
    svg.style.transform = `scale(${zoomLevel})`;
    svg.style.transformOrigin = 'top left';
}

// ================== МЕНЕДЖЕРСКИЙ СПИСОК ==================
function updateManagerStatusList() {
    const list = document.getElementById('manager-status-list');
    if (!list) return;
    list.style.display = 'none';
    list.innerHTML = '';
}
