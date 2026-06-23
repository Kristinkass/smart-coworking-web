// Booking module – 15-minute slots
const SLOT_DURATION = 15;
const MIN_SLOTS = 2;
const MINUTE_OPTIONS = ['00', '15', '30', '45'];

let currentTimegrid = null;
let selectedStartIndex = null;
let selectedDurationSlots = 4;

function roundToSlotMinutes(totalMinutes) {
    return Math.ceil(totalMinutes / SLOT_DURATION) * SLOT_DURATION;
}

function setBookingTimeControlsEnabled(enabled) {
    const tariffType = document.getElementById('tariff-type')?.value || 'hourly';
    const isHourly = tariffType === 'hourly';
    if (!isHourly) return;

    showHourlyBookingTimeUI();

    ['start-hour', 'start-min', 'end-hour', 'end-min'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !enabled;
    });
    document.querySelectorAll('.clock-time-btn').forEach(btn => {
        btn.disabled = !enabled;
    });
    if (window.ClockTimePicker) ClockTimePicker.setEnabled(enabled);

    const bookBtn = document.getElementById('book-btn');
    const noTariff = document.getElementById('no-tariff-hint')?.style.display === 'block';
    if (bookBtn) bookBtn.disabled = !enabled || noTariff;
}

function showHourlyBookingTimeUI() {
    const tariffType = document.getElementById('tariff-type')?.value || 'hourly';
    if (tariffType !== 'hourly') return;

    const hideTimeline = typeof isMobileViewport === 'function' && isMobileViewport();
    const timePicker = document.getElementById('time-picker-row');
    const timegrid = document.getElementById('timegrid-container');
    const durationBtns = document.getElementById('duration-buttons-row');
    const durationRow = document.getElementById('duration-row');
    const hourlyHint = document.getElementById('hourly-hint');

    if (timePicker) timePicker.style.display = '';
    if (timegrid && !hideTimeline) timegrid.style.display = 'block';
    if (durationBtns && !hideTimeline) durationBtns.style.display = 'flex';
    if (durationRow) durationRow.style.display = 'flex';
    if (hourlyHint) hourlyHint.style.display = 'block';
}

function showScheduleStatus(message, type = 'info') {
    const banner = document.getElementById('schedule-status-banner');
    if (!banner) return;
    banner.style.display = 'block';
    banner.className = `schedule-status-banner ${type}`;
    banner.innerHTML = `<i class="fas fa-${type === 'error' ? 'calendar-times' : 'info-circle'}"></i><span>${message}</span>`;
}

function hideScheduleStatus() {
    const banner = document.getElementById('schedule-status-banner');
    if (banner) {
        banner.style.display = 'none';
        banner.textContent = '';
    }
}

function showScheduleHoursInfo(openTime, closeTime) {
    const el = document.getElementById('schedule-hours-info');
    if (!el) return;
    if (openTime && closeTime) {
        el.textContent = `Режим работы: ${openTime} – ${closeTime}`;
        el.style.display = 'block';
    } else {
        el.style.display = 'none';
    }
}

async function loadTimegrid(placeId, date) {
    const timeline = document.getElementById('booking-timeline');
    const tariffType = document.getElementById('tariff-type')?.value || 'hourly';
    if (tariffType !== 'hourly') return;
    const isMobile = typeof isMobileViewport === 'function' && isMobileViewport();

    hideScheduleStatus();
    if (timeline && !isMobile) {
        timeline.innerHTML = '<div class="timeline-loading">Загрузка расписания…</div>';
    }

    try {
        const r = await fetch(`/api/booking/timegrid/${placeId}?date=${date}`);
        const d = await r.json();

        if (!d.success) {
            window.currentSchedule = null;
            currentTimegrid = null;
            window.currentBookingTimegrid = null;
            selectedStartIndex = null;
            if (timeline && !isMobile) {
                timeline.innerHTML = '';
            }
            showScheduleHoursInfo(null, null);
            showScheduleStatus(d.error || 'Нет расписания на этот день', 'error');
            setBookingTimeControlsEnabled(false);
            return;
        }

        const data = d.data;
        window.currentSchedule = {
            open: data.open_time,
            close: data.close_time,
            isBookable: data.is_bookable,
        };
        showScheduleHoursInfo(data.open_time, data.close_time);

        if (!data.slots || data.slots.length === 0) {
            currentTimegrid = null;
            window.currentBookingTimegrid = null;
            selectedStartIndex = null;
            if (timeline && !isMobile) timeline.innerHTML = '';
            showScheduleStatus(
                data.schedule_message || 'Бронирование недоступно в этот день',
                'error',
            );
            setBookingTimeControlsEnabled(false);
            return;
        }

        if (!data.is_bookable) {
            currentTimegrid = data.slots;
            window.currentBookingTimegrid = data.slots;
            selectedStartIndex = null;
            if (typeof rebuildTimeSelects === 'function') {
                rebuildTimeSelects(data.open_time, data.close_time);
            }
            if (!isMobile) {
                if (typeof updateTimegridCapacity === 'function') {
                    updateTimegridCapacity(data);
                }
                renderTimegrid(data);
            }
            showHourlyBookingTimeUI();
            showScheduleStatus(
                data.schedule_message || 'Бронирование недоступно в этот день',
                'error',
            );
            setBookingTimeControlsEnabled(false);
            return;
        }

        hideScheduleStatus();
        showHourlyBookingTimeUI();
        setBookingTimeControlsEnabled(true);
        currentTimegrid = data.slots;
        window.currentBookingTimegrid = data.slots;

        if (typeof rebuildTimeSelects === 'function') {
            rebuildTimeSelects(data.open_time, data.close_time);
        }
        if (!isMobile) {
            if (typeof updateTimegridCapacity === 'function') {
                updateTimegridCapacity(data);
            }
            renderTimegrid(data);
        } else {
            selectedStartIndex = null;
            if (typeof updateDurationDisplay === 'function') updateDurationDisplay();
        }
    } catch (err) {
        console.error(err);
        window.currentSchedule = null;
        currentTimegrid = null;
        window.currentBookingTimegrid = null;
        if (timeline && !isMobile) timeline.innerHTML = '';
        showScheduleStatus('Не удалось загрузить расписание', 'error');
        setBookingTimeControlsEnabled(false);
    }
}

function updateTimegridCapacity(data) {
    const el = document.getElementById('timegrid-capacity');
    if (!el) return;
    let cap = data?.zone_capacity ?? data?.capacity;
    if ((cap == null || cap <= 0) && typeof selectedPlace !== 'undefined' && selectedPlace
        && typeof displayCapacity === 'function') {
        cap = displayCapacity(selectedPlace);
    }
    el.textContent = `Вместимость: ${cap > 0 ? cap : '–'}`;
}

function renderTimegrid(data) {
    const timeline = document.getElementById('booking-timeline');
    if (!timeline) return;

    currentTimegrid = data.slots;
    window.currentBookingTimegrid = data.slots;
    timeline.innerHTML = '';
    selectedStartIndex = null;

    const now = new Date();
    const today = now.toISOString().split('T')[0];
    const selectedDate = document.getElementById('booking-date')?.value || today;
    const isToday = selectedDate === today;
    const currentTotalMinutes = now.getHours() * 60 + now.getMinutes();
    const minFutureMinutes = isToday ? roundToSlotMinutes(currentTotalMinutes) : 0;

    if (!data.slots || data.slots.length === 0) {
        timeline.innerHTML = '<div class="timeline-empty">Нет доступных слотов на этот день</div>';
        return;
    }

    const visibleSlots = data.slots
        .map((slotData, slotIndex) => ({ slotData, slotIndex }))
        .filter(({ slotData }) => {
            if (slotData.is_past) return false;
            const [hour, minute] = slotData.time.split(':').map(Number);
            const totalMinutes = hour * 60 + minute;
            if (isToday && totalMinutes < minFutureMinutes) return false;
            return true;
        });

    if (!visibleSlots.length) {
        timeline.innerHTML = '<div class="timeline-empty">На сегодня бронирование уже недоступно</div>';
        return;
    }

    visibleSlots.forEach(({ slotData, slotIndex }) => {
        const timeStr = slotData.time;

        const slot = document.createElement('div');
        slot.className = 'timeline-slot';
        slot.dataset.index = slotIndex;
        slot.dataset.time = timeStr;

        if (slotData.status === 'full') {
            slot.classList.add('occupied');
        } else if (slotData.status === 'partial') {
            slot.classList.add('partial');
        } else {
            slot.classList.add('available');
        }

        slot.addEventListener('click', function () {
            if (this.classList.contains('occupied')) {
                if (typeof showAlert === 'function') showAlert('Это время недоступно', 'warning');
                return;
            }
            selectStartSlot(slotIndex);
        });

        timeline.appendChild(slot);
    });

    addTimelineLabels(visibleSlots.map(({ slotData }) => slotData));
}

function addTimelineLabels(slots) {
    const container = document.querySelector('.timeline-container');
    const oldLabels = container?.querySelector('.timeline-labels');
    if (oldLabels) oldLabels.remove();
    if (!slots || slots.length === 0) return;

    const labelsDiv = document.createElement('div');
    labelsDiv.className = 'timeline-labels';

    slots.forEach((slot) => {
        const [, minute] = slot.time.split(':').map(Number);
        const label = document.createElement('div');
        label.className = 'timeline-label';
        label.textContent = minute === 0 ? slot.time : '';
        labelsDiv.appendChild(label);
    });

    container?.appendChild(labelsDiv);
}

function selectStartSlot(index) {
    selectedStartIndex = index;
    if (!selectedDurationSlots) selectedDurationSlots = MIN_SLOTS;

    const slot = currentTimegrid?.[index];
    if (!slot) return;

    const [h, m] = slot.time.split(':');
    const startTotalMins = parseInt(h, 10) * 60 + parseInt(m, 10);

    const hours = typeof getCoworkingHours === 'function'
        ? getCoworkingHours()
        : { close: 22 * 60 };

    const endTotalMins = startTotalMins + (selectedDurationSlots * SLOT_DURATION);
    if (endTotalMins > hours.close) {
        const maxSlots = Math.floor((hours.close - startTotalMins) / SLOT_DURATION);
        if (maxSlots >= MIN_SLOTS) {
            selectedDurationSlots = maxSlots;
            const closeH = Math.floor(hours.close / 60);
            const closeM = hours.close % 60;
            const closeTimeStr = String(closeH).padStart(2, '0') + ':' + String(closeM).padStart(2, '0');
            if (typeof showAlert === 'function') {
                showAlert(`Длительность скорректирована до времени закрытия (${closeTimeStr})`, 'warning');
            }
        } else {
            if (typeof showAlert === 'function') {
                showAlert('Недостаточно времени до закрытия. Выберите более раннее время.', 'error');
            }
            return;
        }
    }

    document.getElementById('start-hour').value = h;
    document.getElementById('start-min').value = m;

    highlightRange();
    updateEndTimeFromDuration();
    updateDurationDisplay();
    if (typeof onTimeChange === 'function') onTimeChange();
}

function highlightRange() {
    const timeline = document.getElementById('booking-timeline');
    if (!timeline) return;

    const slots = timeline.querySelectorAll('.timeline-slot');
    const endIndex = selectedStartIndex + selectedDurationSlots;

    slots.forEach((s, i) => {
        s.classList.remove('selected', 'selected-start', 'selected-end', 'in-range');
        if (selectedStartIndex === null) return;

        if (i === selectedStartIndex) {
            s.classList.add('selected', 'selected-start');
        } else if (i === endIndex - 1) {
            s.classList.add('selected', 'selected-end');
        } else if (i > selectedStartIndex && i < endIndex) {
            s.classList.add('in-range');
        }
    });
}

function changeDuration(delta) {
    const newDuration = selectedDurationSlots + delta;
    if (newDuration < MIN_SLOTS) {
        if (typeof showAlert === 'function') showAlert('Минимальное время: 30 минут', 'warning');
        return;
    }
    if (newDuration > 32) {
        if (typeof showAlert === 'function') showAlert('Максимальное время: 8 часов', 'warning');
        return;
    }
    selectedDurationSlots = newDuration;
    updateDurationDisplay();
    highlightRange();
    updateEndTimeFromDuration();
    if (typeof onTimeChange === 'function') onTimeChange();
}

function setDuration(mins) {
    if (mins < MIN_SLOTS * SLOT_DURATION) mins = MIN_SLOTS * SLOT_DURATION;
    selectedDurationSlots = Math.ceil(mins / SLOT_DURATION);

    if (selectedStartIndex !== null) {
        selectStartSlot(selectedStartIndex);
        return;
    }

    const startH = parseInt(document.getElementById('start-hour')?.value || '9', 10);
    const startM = parseInt(document.getElementById('start-min')?.value || '0', 10);
    const hours = typeof getCoworkingHours === 'function' ? getCoworkingHours() : { close: 22 * 60 };
    const endTotalMins = startH * 60 + startM + selectedDurationSlots * SLOT_DURATION;

    if (endTotalMins > hours.close) {
        const maxDuration = hours.close - (startH * 60 + startM);
        if (maxDuration < MIN_SLOTS * SLOT_DURATION) {
            if (typeof showAlert === 'function') showAlert('Недостаточно времени до закрытия', 'warning');
            return;
        }
        selectedDurationSlots = Math.floor(maxDuration / SLOT_DURATION);
    }

    updateEndTimeFromDuration();
    updateDurationDisplay();
    if (typeof syncTimelineWithSelects === 'function') syncTimelineWithSelects();
    if (typeof onTimeChange === 'function') onTimeChange();
}

function updateEndTimeFromDuration() {
    if (selectedStartIndex === null || !currentTimegrid) {
        const startH = parseInt(document.getElementById('start-hour')?.value || '0', 10);
        const startM = parseInt(document.getElementById('start-min')?.value || '0', 10);
        const startTotalMinutes = startH * 60 + startM;
        const endTotalMinutes = startTotalMinutes + selectedDurationSlots * SLOT_DURATION;
        document.getElementById('end-hour').value = String(Math.floor(endTotalMinutes / 60)).padStart(2, '0');
        document.getElementById('end-min').value = String(endTotalMinutes % 60).padStart(2, '0');
        return;
    }

    const startSlot = currentTimegrid[selectedStartIndex];
    if (!startSlot) return;
    const [h, m] = startSlot.time.split(':').map(Number);
    const endTotalMinutes = h * 60 + m + selectedDurationSlots * SLOT_DURATION;
    document.getElementById('end-hour').value = String(Math.floor(endTotalMinutes / 60)).padStart(2, '0');
    document.getElementById('end-min').value = String(endTotalMinutes % 60).padStart(2, '0');
}

function formatDuration(slots) {
    const mins = slots * SLOT_DURATION;
    const hours = Math.floor(mins / 60);
    const minutes = mins % 60;
    if (hours === 0) return minutes + ' мин';
    if (minutes === 0) return hours + ' ' + (hours === 1 ? 'час' : hours < 5 ? 'часа' : 'часов');
    return hours + ' ' + (hours === 1 ? 'час' : hours < 5 ? 'часа' : 'часов') + ' ' + minutes + ' мин';
}

function updateDurationDisplay() {
    const el = document.getElementById('duration-display');
    if (!el) return;
    if (selectedDurationSlots) {
        el.textContent = formatDuration(selectedDurationSlots);
    } else {
        const start = document.getElementById('start-hour')?.value + ':' + document.getElementById('start-min')?.value;
        const end = document.getElementById('end-hour')?.value + ':' + document.getElementById('end-min')?.value;
        const [sh, sm] = start.split(':').map(Number);
        const [eh, em] = end.split(':').map(Number);
        const diff = (eh * 60 + em) - (sh * 60 + sm);
        el.textContent = diff >= MIN_SLOTS * SLOT_DURATION ? formatDuration(Math.ceil(diff / SLOT_DURATION)) : '-';
    }
}

function syncTimelineWithSelects() {
    if (!currentTimegrid || currentTimegrid.length === 0) return;

    const startH = parseInt(document.getElementById('start-hour')?.value || 8, 10);
    const startM = parseInt(document.getElementById('start-min')?.value || 0, 10);
    const endH = parseInt(document.getElementById('end-hour')?.value || 9, 10);
    const endM = parseInt(document.getElementById('end-min')?.value || 0, 10);

    const startTotalMinutes = startH * 60 + startM;
    const endTotalMinutes = endH * 60 + endM;
    if (endTotalMinutes <= startTotalMinutes) return;

    const firstSlot = currentTimegrid[0];
    const [fh, fm] = firstSlot.time.split(':').map(Number);
    const firstMinutes = fh * 60 + fm;

    const startIndex = Math.round((startTotalMinutes - firstMinutes) / SLOT_DURATION);
    const durationMinutes = endTotalMinutes - startTotalMinutes;
    const durationSlots = Math.max(MIN_SLOTS, Math.round(durationMinutes / SLOT_DURATION));

    if (startIndex >= 0 && startIndex < currentTimegrid.length) {
        selectedStartIndex = startIndex;
        selectedDurationSlots = durationSlots;
        highlightRange();
        updateDurationDisplay();
    }
}

async function updatePrice() {
    if (!selectedPlace) return;
    if (typeof schedulePriceDisplayUpdate === 'function') {
        schedulePriceDisplayUpdate();
    } else if (typeof updatePriceDisplay === 'function') {
        updatePriceDisplay();
    }
}

async function checkBooking(placeId, date, start, end, people, tariffType) {
    const r = await fetch('/api/booking/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            place_id: placeId,
            date,
            start_time: start,
            end_time: end,
            people_count: people,
            tariff_type: tariffType || 'hourly'
        })
    });
    return await r.json();
}

async function createBookingModule(placeId, date, start, end, people, tariffType, userId, useSubscription) {
    const payload = {
        place_id: placeId,
        date,
        start_time: start,
        end_time: end,
        people_count: people,
        tariff_type: tariffType || 'hourly'
    };
    if (userId) payload.user_id = userId;
    if (useSubscription === false) payload.use_subscription = false;
    const r = await fetch('/api/booking/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
    });
    return await r.json();
}

async function fetchBookingPrice(placeId, start, end, people, tariffType, opts) {
    const date = (opts && opts.date) || document.getElementById('booking-date')?.value || null;
    const noSub = (opts && opts.noSubscription) || false;
    const r = await fetch('/api/booking/price', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            place_id: placeId,
            start_time: start,
            end_time: end,
            people_count: people,
            tariff_type: tariffType || 'hourly',
            date: date,
            no_subscription: noSub,
        })
    });
    return await r.json();
}

function resetBookingSelection() {
    selectedStartIndex = null;
    selectedDurationSlots = 4;
    const timeline = document.getElementById('booking-timeline');
    if (timeline) {
        timeline.querySelectorAll('.timeline-slot').forEach(s => {
            s.classList.remove('selected', 'selected-start', 'selected-end', 'in-range');
        });
    }
}

async function bookWithSubscription(subscriptionId, placeId, date, start, end, userId) {
    const payload = {
        subscription_id: subscriptionId,
        place_id: placeId,
        date,
        start_time: start,
        end_time: end
    };
    if (userId) payload.user_id = userId;
    const r = await fetch('/api/subscription/book', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return await r.json();
}
