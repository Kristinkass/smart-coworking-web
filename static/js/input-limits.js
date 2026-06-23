(function () {
    'use strict';

    const lastShown = new WeakMap();

    function notify(message) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, 'warning');
        } else if (typeof window.showAlert === 'function') {
            window.showAlert(message, 'warning');
        } else if (typeof window.showNotification === 'function') {
            window.showNotification(message, 'warning');
        }
    }

    function labelFor(el) {
        const explicit = el.id ? document.querySelector(`label[for="${el.id}"]`) : null;
        if (explicit) return explicit.textContent.trim();
        const groupLabel = el.closest('.form-group, .field, td, div')?.querySelector('label');
        if (groupLabel) return groupLabel.textContent.trim();
        return el.getAttribute('aria-label') || el.name || 'Значение';
    }

    function showOnce(el, message) {
        const prev = lastShown.get(el);
        const now = Date.now();
        if (prev && prev.message === message && now - prev.at < 1800) return;
        lastShown.set(el, { message, at: now });
        notify(message);
    }

    function numericValue(el) {
        if (el.value === '') return null;
        const value = Number(el.value);
        return Number.isFinite(value) ? value : null;
    }

    function validateNumber(el) {
        if (el.type !== 'number') return;
        const value = numericValue(el);
        if (value === null) return;

        const label = labelFor(el);
        if (el.max !== '' && value > Number(el.max)) {
            el.value = el.max;
            showOnce(el, `${label}: максимум ${el.max}`);
        } else if (el.min !== '' && value < Number(el.min)) {
            el.value = el.min;
            showOnce(el, `${label}: минимум ${el.min}`);
        }
    }

    function validateLength(el) {
        if (!('maxLength' in el) || el.maxLength <= 0) return;
        if (el.value.length <= el.maxLength) return;

        const label = labelFor(el);
        el.value = el.value.slice(0, el.maxLength);
        showOnce(el, `${label}: не больше ${el.maxLength} символов`);
    }

    function validate(el) {
        if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
        validateNumber(el);
        validateLength(el);
    }

    document.addEventListener('beforeinput', (e) => {
        const el = e.target;
        if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
        if (!('maxLength' in el) || el.maxLength <= 0) return;
        if (!e.data) return;

        const start = el.selectionStart ?? el.value.length;
        const end = el.selectionEnd ?? el.value.length;
        const nextLength = el.value.length - (end - start) + e.data.length;
        if (nextLength > el.maxLength) {
            showOnce(el, `${labelFor(el)}: не больше ${el.maxLength} символов`);
        }
    }, true);
    document.addEventListener('input', (e) => validate(e.target), true);
    document.addEventListener('change', (e) => validate(e.target), true);
    document.addEventListener('blur', (e) => validate(e.target), true);
})();
