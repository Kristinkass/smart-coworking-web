/**
 * Выбор времени через циферблат (вместо нативных select на мобильных).
 */
'use strict';

(function () {
    let activeField = null;
    let availableHours = [];
    let disabledStartHours = new Set();
    let disabledEndHours = new Set();
    let disabledStartMinutes = new Set();
    let disabledEndMinutes = new Set();
    let selectedHour = 10;
    let selectedMinute = '00';

    function $(id) { return document.getElementById(id); }

    function pad2(n) { return String(n).padStart(2, '0'); }

    function getFieldValues(field) {
        const prefix = field === 'start' ? 'start' : 'end';
        return {
            hour: $(`${prefix}-hour`)?.value || '10',
            minute: $(`${prefix}-min`)?.value || '00',
        };
    }

    function setFieldValues(field, hour, minute) {
        const prefix = field === 'start' ? 'start' : 'end';
        const hEl = $(`${prefix}-hour`);
        const mEl = $(`${prefix}-min`);
        if (hEl) hEl.value = pad2(parseInt(hour, 10));
        if (mEl) mEl.value = minute;
        updateDisplays();
    }

    function updateDisplays() {
        const start = getFieldValues('start');
        const end = getFieldValues('end');
        const startEl = $('clock-start-display');
        const endEl = $('clock-end-display');
        if (startEl) startEl.textContent = `${start.hour}:${start.minute}`;
        if (endEl) endEl.textContent = `${end.hour}:${end.minute}`;
    }

    function renderDial() {
        const dial = $('clock-dial');
        if (!dial) return;
        dial.innerHTML = '';
        const disabled = activeField === 'start' ? disabledStartHours : disabledEndHours;
        const size = 220;
        const cx = size / 2;
        const cy = size / 2;
        const radius = 78;

        const face = document.createElement('div');
        face.className = 'clock-dial-face';
        face.style.width = `${size}px`;
        face.style.height = `${size}px`;

        availableHours.forEach((h, i) => {
            const angle = (i / availableHours.length) * 2 * Math.PI - Math.PI / 2;
            const x = cx + radius * Math.cos(angle);
            const y = cy + radius * Math.sin(angle);
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'clock-hour-btn';
            btn.textContent = pad2(h);
            btn.style.left = `${x}px`;
            btn.style.top = `${y}px`;
            if (disabled.has(h)) {
                btn.disabled = true;
                btn.classList.add('disabled');
            }
            if (parseInt(selectedHour, 10) === h) btn.classList.add('active');
            btn.addEventListener('click', () => {
                if (disabled.has(h)) return;
                selectedHour = h;
                renderDial();
                renderMinutes();
            });
            face.appendChild(btn);
        });

        const center = document.createElement('div');
        center.className = 'clock-dial-center';
        center.textContent = `${pad2(selectedHour)}:${selectedMinute}`;
        face.appendChild(center);
        dial.appendChild(face);
    }

    function renderMinutes() {
        const row = $('clock-minutes');
        if (!row) return;
        row.innerHTML = '';
        const disabled = activeField === 'start' ? disabledStartMinutes : disabledEndMinutes;
        ['00', '15', '30', '45'].forEach(mm => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'clock-min-btn';
            btn.textContent = mm;
            btn.dataset.min = mm;
            if (disabled.has(mm)) {
                btn.disabled = true;
                btn.classList.add('disabled');
            }
            if (selectedMinute === mm) btn.classList.add('active');
            btn.addEventListener('click', () => {
                if (disabled.has(mm)) return;
                selectedMinute = mm;
                setFieldValues(activeField, selectedHour, selectedMinute);
                renderDial();
                renderMinutes();
                if (typeof onTimeChange === 'function') onTimeChange();
            });
            row.appendChild(btn);
        });
    }

    function openClockPicker(field) {
        activeField = field;
        const vals = getFieldValues(field);
        selectedHour = parseInt(vals.hour, 10) || availableHours[0] || 10;
        selectedMinute = vals.minute || '00';
        const title = $('clock-modal-title');
        if (title) title.textContent = field === 'start' ? 'Время начала' : 'Время окончания';
        const modal = $('clock-picker-modal');
        if (modal) modal.classList.add('visible');
        renderDial();
        renderMinutes();
    }

    function closeClockPicker() {
        const modal = $('clock-picker-modal');
        if (modal) modal.classList.remove('visible');
        activeField = null;
    }

    function setAvailableHours(hours) {
        availableHours = hours.slice();
    }

    function setDisabledHours(field, hoursSet) {
        if (field === 'start') disabledStartHours = hoursSet;
        else disabledEndHours = hoursSet;
    }

    function setDisabledMinutes(field, minutesSet) {
        if (field === 'start') disabledStartMinutes = minutesSet;
        else disabledEndMinutes = minutesSet;
    }

    function setEnabled(enabled) {
        ['clock-start-btn', 'clock-end-btn'].forEach(id => {
            const el = $(id);
            if (el) el.disabled = !enabled;
        });
        ['start-hour', 'start-min', 'end-hour', 'end-min'].forEach(id => {
            const el = $(id);
            if (el) el.disabled = !enabled;
        });
    }

    window.openClockPicker = openClockPicker;
    window.closeClockPicker = closeClockPicker;
    window.ClockTimePicker = {
        setAvailableHours,
        setDisabledHours,
        setDisabledMinutes,
        updateDisplays,
        setEnabled,
        refresh: updateDisplays,
    };
})();
