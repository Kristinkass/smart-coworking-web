/**
 * Отображение мест: код, подписи, форматирование.
 */
'use strict';

function normalizePlaceSegment(code, locationCode) {
    code = (code || '').trim();
    locationCode = (locationCode || '').trim();
    if (!code) return locationCode;
    if (locationCode && code !== locationCode && !code.startsWith(`${locationCode}-`)) {
        return `${locationCode}-${code.replace(/^-/, '')}`;
    }
    return code;
}

function formatPlaceCode(place) {
    if (!place) return '–';
    const code = (place.code || '').trim();
    const locCode = (place.location_code || '').trim();
    return normalizePlaceSegment(code, locCode) || '–';
}

function formatPlaceFullCode(place, placesByCode) {
    if (!place) return '–';
    if (place.full_code) return place.full_code;

    const locCode = (place.location_code || '').trim();
    const segments = [];
    if (locCode) segments.push(locCode);

    if (place.kind === 'desk' && place.container_code) {
        const parent = placesByCode && placesByCode[place.container_code];
        const parentLoc = ((parent && parent.location_code) || locCode).trim();
        const parentSeg = normalizePlaceSegment(place.container_code, parentLoc || locCode);
        if (parentSeg && !segments.includes(parentSeg)) segments.push(parentSeg);
    }

    const placeSeg = normalizePlaceSegment(place.code, locCode);
    if (placeSeg && !segments.includes(placeSeg)) segments.push(placeSeg);
    return segments.length ? segments.join(' · ') : '–';
}

function placeLabelWithCode(place) {
    if (!place) return '';
    const name = (place.name || '').trim();
    const code = formatPlaceCode(place);
    if (name && code && name !== code) return `${name} (${code})`;
    return name || code;
}

function placeDisplayName(place) {
    const name = (place.name || '').trim();
    if (name) return name;
    return formatPlaceCode(place);
}

function formatRubles(amount) {
    const n = Math.round(Number(amount) || 0);
    return n.toLocaleString('ru-RU') + ' ₽';
}

function placeSizeLabel(place) {
    if (place.size_label) return place.size_label;
    if (place.width_m && place.height_m) return `${place.width_m}×${place.height_m} м`;
    return null;
}

function placeTypeLabel(place) {
    if (place.kind === 'desk') return 'Рабочий стол';
    if (place.is_meeting_room || place.category?.kind === 'room') return 'Переговорная';
    if (typeof isDeskZoneSpace === 'function' && isDeskZoneSpace(place)) return 'Зона рабочих столов';
    if (typeof isSpaceContainer === 'function' && isSpaceContainer(place)) return 'Помещение';
    return 'Место';
}
