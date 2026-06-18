/**
 * Russian phone mask: +7 999 123 45 67 (spaces, no dashes).
 */
(function (global) {
    'use strict';

    function formatPhoneDigits(digits) {
        if (digits.startsWith('8')) digits = '7' + digits.slice(1);
        if (digits.startsWith('7')) digits = digits.slice(1);
        digits = digits.slice(0, 10);

        let out = '+7';
        if (digits.length > 0) out += ' ' + digits.slice(0, 3);
        if (digits.length > 3) out += ' ' + digits.slice(3, 6);
        if (digits.length > 6) out += ' ' + digits.slice(6, 8);
        if (digits.length > 8) out += ' ' + digits.slice(8, 10);
        return out;
    }

    function formatPhoneValue(value) {
        const digits = String(value || '').replace(/\D/g, '');
        if (!digits) return '';
        return formatPhoneDigits(digits);
    }

    function attachPhoneMask(input) {
        if (!input || input.dataset.phoneMaskBound) return;

        const onInput = function (e) {
            const formatted = formatPhoneValue(e.target.value);
            e.target.value = formatted;
            e.target.setSelectionRange(formatted.length, formatted.length);
        };

        const onKeydown = function (e) {
            if (e.key !== 'Backspace') return;
            const value = e.target.value;
            if (value.length > 0 && /[\s]/.test(value[value.length - 1])) {
                e.preventDefault();
                e.target.value = value.slice(0, -1);
                const len = e.target.value.length;
                e.target.setSelectionRange(len, len);
            }
        };

        const onFocus = function () {
            if (!this.value || this.value === '+7') this.value = '+7 ';
        };

        const onBlur = function () {
            if (this.value === '+7' || this.value === '+7 ') this.value = '';
        };

        input.addEventListener('input', onInput);
        input.addEventListener('keydown', onKeydown);
        input.addEventListener('focus', onFocus);
        input.addEventListener('blur', onBlur);

        input._phoneMaskHandlers = { onInput, onKeydown, onFocus, onBlur };
        input.dataset.phoneMaskBound = '1';
        input.classList.add('phone-mask');
        input.setAttribute('inputmode', 'tel');
        input.setAttribute('autocomplete', 'tel');

        if (input.value) {
            input.value = formatPhoneValue(input.value);
        }
    }

    function detachPhoneMask(input) {
        if (!input || !input._phoneMaskHandlers) return;
        const h = input._phoneMaskHandlers;
        input.removeEventListener('input', h.onInput);
        input.removeEventListener('keydown', h.onKeydown);
        input.removeEventListener('focus', h.onFocus);
        input.removeEventListener('blur', h.onBlur);
        delete input._phoneMaskHandlers;
        delete input.dataset.phoneMaskBound;
        input.classList.remove('phone-mask');
        input.removeAttribute('inputmode');
    }

    function initPhoneMasks(root) {
        const scope = root || document;
        scope.querySelectorAll('input[type="tel"], input.phone-mask').forEach(attachPhoneMask);
    }

    function phoneDigits(value) {
        return String(value || '').replace(/\D/g, '');
    }

    function isPhoneComplete(value) {
        const digits = phoneDigits(value);
        return digits.length === 11 && digits.startsWith('7');
    }

    global.formatPhoneValue = formatPhoneValue;
    global.attachPhoneMask = attachPhoneMask;
    global.detachPhoneMask = detachPhoneMask;
    global.initPhoneMasks = initPhoneMasks;
    global.phoneDigits = phoneDigits;
    global.isPhoneComplete = isPhoneComplete;

    document.addEventListener('DOMContentLoaded', function () {
        initPhoneMasks();
    });
})(window);
