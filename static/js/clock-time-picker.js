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
    let pickerStep = 'hour';

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

    function syncSelectedFromField() {
        if (!activeField) return;
        const vals = getFieldValues(activeField);
        selectedHour = parseInt(vals.hour, 10) || selectedHour;
        selectedMinute = vals.minute || selectedMinute;
    }

    function minuteOptions() {
        return ['00', '15', '30', '45'];
    }

    function renderPickerHeader() {
        const title = $('clock-modal-title');
        if (!title) return;
        const fieldLabel = activeField === 'start' ? 'Начало' : 'Конец';
        title.innerHTML = `
            <div class="clock-modal-label">${fieldLabel}</div>
            <button type="button" class="clock-modal-value ${pickerStep === 'hour' ? 'active' : ''}" data-step="hour">${pad2(selectedHour)}</button>
            <span class="clock-modal-sep">:</span>
            <button type="button" class="clock-modal-value ${pickerStep === 'minute' ? 'active' : ''}" data-step="minute">${selectedMinute}</button>
        `;
        title.querySelectorAll('[data-step]').forEach(btn => {
            btn.addEventListener('click', () => {
                pickerStep = btn.dataset.step;
                renderDial();
                renderMinutes();
            });
        });
    }

    function renderDial() {
        const dial = $('clock-dial');
        if (!dial) return;
        dial.innerHTML = '';
        renderPickerHeader();

        const isMinuteStep = pickerStep === 'minute';
        const values = isMinuteStep ? minuteOptions() : availableHours;
        const disabled = isMinuteStep
            ? (activeField === 'start' ? disabledStartMinutes : disabledEndMinutes)
            : (activeField === 'start' ? disabledStartHours : disabledEndHours);
        const size = 220;
        const cx = size / 2;
        const cy = size / 2;
        const radius = 78;

        const face = document.createElement('div');
        face.className = 'clock-dial-face';
        face.style.width = `${size}px`;
        face.style.height = `${size}px`;

        values.forEach((value, i) => {
            const angle = (i / values.length) * 2 * Math.PI - Math.PI / 2;
            const x = cx + radius * Math.cos(angle);
            const y = cy + radius * Math.sin(angle);
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'clock-hour-btn';
            btn.textContent = isMinuteStep ? value : pad2(value);
            btn.style.left = `${x}px`;
            btn.style.top = `${y}px`;
            const disabledKey = isMinuteStep ? value : value;
            if (disabled.has(disabledKey)) {
                btn.disabled = true;
                btn.classList.add('disabled');
            }
            if ((isMinuteStep && selectedMinute === value) ||
                (!isMinuteStep && parseInt(selectedHour, 10) === value)) {
                btn.classList.add('active');
            }
            btn.addEventListener('click', () => {
                if (disabled.has(disabledKey)) return;
                if (isMinuteStep) {
                    selectedMinute = value;
                    setFieldValues(activeField, selectedHour, selectedMinute);
                    if (typeof onTimeChange === 'function') onTimeChange();
                    syncSelectedFromField();
                } else {
                    selectedHour = value;
                    setFieldValues(activeField, selectedHour, selectedMinute);
                    if (typeof onTimeChange === 'function') onTimeChange();
                    syncSelectedFromField();
                    pickerStep = 'minute';
                }
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
        row.textContent = pickerStep === 'hour' ? 'Выберите час' : 'Выберите минуты';
    }

    function openClockPicker(field) {
        activeField = field;
        const vals = getFieldValues(field);
        selectedHour = parseInt(vals.hour, 10) || availableHours[0] || 10;
        selectedMinute = vals.minute || '00';
        pickerStep = 'hour';
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
