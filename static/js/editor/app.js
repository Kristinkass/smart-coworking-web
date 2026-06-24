/**
 * Редактор планировки v2 – единая модель локаций.
 */
(function () {
  'use strict';

  const SVG_W = 2240, SVG_H = 1344, SCALE = 100;
  const WALL_HALF = 8, FLOOR_INSET = 8, PARENT_INSET = 8, WALL_PENETRATION = 0;
  const DOOR_W_1M = 100, DOOR_W_15M = 150;

  let places = [], walls = [], doors = [], wallRooms = [];
  let categories = [], locationZones = [];
  let currentFloor = 1, zoomLevel = 1;
  let availableFloors = [{ number: 1, label: 'Этаж 1' }];
  let wallMode = false, doorMode = false, wallMoveMode = false, wallStart = null;
  let selection = null; // { type: 'location'|'desk', room, place, draft }
  let variants = [], variantMode = 'desks';
  let variantsRequestSeq = 0;
  let _createBusy = false, _tplBound = false;

  const $ = id => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function friendlyError(error, fallback = 'Что-то пошло не так') {
    const raw = String(error?.message || error || fallback);
    if (/Cannot read properties|undefined|null is not|is not a function/i.test(raw)) {
      return 'Редактор не смог прочитать данные локации. Обновите карту и попробуйте ещё раз.';
    }
    if (/Failed to fetch|NetworkError|Load failed/i.test(raw)) {
      return 'Нет связи с сервером. Проверьте, что приложение запущено.';
    }
    if (/Unexpected token|JSON/i.test(raw)) {
      return 'Сервер вернул повреждённый ответ. Обновите страницу или перезапустите приложение.';
    }
    if (/Traceback|Stack trace|TypeError|ReferenceError|SyntaxError|AttributeError|KeyError/i.test(raw)) {
      return fallback;
    }
    if (/^[\x00-\x7F]+$/.test(raw) && /[a-z]/i.test(raw)) {
      return fallback;
    }
    return raw.replace(/^Error:\s*/i, '') || fallback;
  }

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(friendlyError(data.error || data.message || ('Ошибка ' + r.status), 'Ошибка ' + r.status));
    if (data.success === false) throw new Error(friendlyError(data.error || data.message || 'Ошибка запроса'));
    return data;
  }

  function toast(msg, type) {
    const t = document.createElement('div');
    const kind = type || 'info';
    const icons = { success: 'check-circle', error: 'exclamation-triangle', warning: 'exclamation-circle', info: 'info-circle' };
    t.className = 'toast ' + kind;
    t.innerHTML = `<i class="fas fa-${icons[kind] || icons.info}"></i><span>${escapeHtml(friendlyError(msg, 'Готово'))}</span>`;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s, transform .3s'; t.style.transform = 'translateY(-6px)'; }, 3200);
    setTimeout(() => t.remove(), 3600);
  }

  const toastLimiter = new Map();
  function toastLimited(key, msg, type, delay = 1400) {
    const now = Date.now();
    if (now - (toastLimiter.get(key) || 0) < delay) return;
    toastLimiter.set(key, now);
    toast(msg, type);
  }

  let confirmToastEl = null;
  function hideConfirmToast() {
    if (confirmToastEl) {
      confirmToastEl.remove();
      confirmToastEl = null;
    }
  }

  function askConfirm(message, onYes, yesLabel, opts = {}) {
    hideConfirmToast();
    const el = document.createElement('div');
    el.className = 'confirm-toast';
    el.innerHTML = `<div class="confirm-title"><i class="fas fa-${opts.icon || 'question-circle'}"></i>${escapeHtml(opts.title || 'Подтвердите действие')}</div>
    <span>${escapeHtml(message)}</span><div class="confirm-actions">
      <button type="button" class="confirm-no">Отмена</button>
      <button type="button" class="confirm-yes">${escapeHtml(yesLabel || 'Удалить')}</button>
    </div>`;
    el.querySelector('.confirm-yes').addEventListener('click', () => {
      hideConfirmToast();
      onYes();
    });
    el.querySelector('.confirm-no').addEventListener('click', hideConfirmToast);
    document.body.appendChild(el);
    confirmToastEl = el;
  }

  function selectedZone() {
    return zoneById($('prop-location-zone')?.value);
  }

  function zoneLabel(z) {
    if (!z) return '–';
    return z.name || (z.letter ? `Зона ${z.letter}` : '–');
  }

  function zoneKindFlags(z) {
    z = z || selectedZone();
    const amenity = isAmenityZone(z);
    return {
      z,
      amenity,
      meeting: !amenity && isRoomZone(z),
      desk: !amenity && isDeskZone(z),
      label: zoneLabel(z),
    };
  }

  function zoneForPlace(place) {
    if (!place) return null;
    if (place.zone_type?.kind) return place.zone_type;
    if (place.zone_type_id) return zoneById(place.zone_type_id) || null;
    return null;
  }

  function isMeetingPlace(place) {
    const z = zoneForPlace(place);
    if (z) return isRoomZone(z);
    return !!place?.is_meeting_room;
  }

  function isAmenityPlace(place) {
    const z = zoneForPlace(place);
    if (z) return isAmenityZone(z);
    return place?.bookable === false;
  }

  function placeZoneSub(p) {
    const z = zoneForPlace(p);
    if (z?.name) return z.name;
    if (isMeetingPlace(p)) return 'Переговорная';
    if (p?.allows_desks !== false) return 'Зона столов';
    return '–';
  }

  function deskBlockedMessage(place) {
    if (isMeetingPlace(place)) {
      return 'В переговорную нельзя класть столы – используйте «Варианты размещения»';
    }
    const zn = placeZoneSub(place);
    if (zn && zn !== '–') return `В «${zn}» столы нельзя размещать`;
    return 'Столы здесь не разрешены';
  }

  function snapWallPoint(pt) {
    const SNAP = 16;
    let best = { x: Math.round(pt.x), y: Math.round(pt.y), d: SNAP + 1 };
    floorWalls().forEach(w => {
      [{ x: w.x1, y: w.y1 }, { x: w.x2, y: w.y2 }].forEach(p => {
        const d = Math.hypot(pt.x - p.x, pt.y - p.y);
        if (d < best.d) best = { x: p.x, y: p.y, d };
      });
      const dx = w.x2 - w.x1, dy = w.y2 - w.y1, len2 = dx * dx + dy * dy;
      if (len2 > 1) {
        const t = Math.max(0, Math.min(1, ((pt.x - w.x1) * dx + (pt.y - w.y1) * dy) / len2));
        const px = w.x1 + t * dx, py = w.y1 + t * dy;
        const d = Math.hypot(pt.x - px, pt.y - py);
        if (d < best.d) best = { x: Math.round(px), y: Math.round(py), d };
      }
    });
    return { x: best.x, y: best.y };
  }

  function handleWallModeClick(pt) {
    const snapped = snapWallPoint(pt);
    if (!wallStart) {
      wallStart = snapped;
      toast('Начало стены – кликните конец (можно по другой стене)', 'info');
      return;
    }
    createWall(wallStart, snapped);
    wallStart = null;
  }

  function zoneById(id) {
    return locationZones.find(z => z.id === parseInt(id, 10));
  }

  function isDeskZone(zone) {
    return zone && zone.kind === 'desk_zone';
  }

  function isAmenityZone(zone) {
    return zone && ['amenity_zone', 'lounge_zone', 'kitchen_zone', 'wc_zone'].includes(zone.kind);
  }

  function isRoomZoneKind(zone) {
    return zone && zone.kind === 'room_zone';
  }

  function allowsDesks(place) {
    if (!place || place.bookable === false || isAmenityPlace(place)) return false;
    const z = zoneForPlace(place);
    if (z) return isDeskZone(z);
    return place.allows_desks !== false && !isMeetingPlace(place);
  }

  function allowsLayoutItems(place) {
    return place && (place.kind === 'space' || place.kind === 'room');
  }

  const DESK_GAP = 0;

  function desksEffectiveOverlap(ax, ay, aw, ah, aRot, bx, by, bw, bh, bRot, gap = DESK_GAP) {
    const a = effectiveRectForRotation(ax, ay, aw, ah, aRot);
    const b = effectiveRectForRotation(bx, by, bw, bh, bRot);
    return rectsOverlap(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h, gap);
  }

  function deskParent(desk) {
    if (desk.container_code) {
      const linked = places.find(p => p.code === desk.container_code);
      if (linked) return linked;
    }
    if (!desk || desk.width == null || desk.height == null) return null;
    return floorPlaces().find(p =>
      (p.kind === 'space' || p.kind === 'room') &&
      desk.x + desk.width / 2 >= p.x && desk.x + desk.width / 2 <= p.x + p.width &&
      desk.y + desk.height / 2 >= p.y && desk.y + desk.height / 2 <= p.y + p.height
    );
  }

  function zoneSeatCapacity(space) {
    if (!space) return 0;
    return places
      .filter(p => p.kind === 'desk' && p.container_code === space.code)
      .reduce((s, d) => s + (d.capacity || d.category?.capacity || 1), 0);
  }

  function desksInLocation(space) {
    if (!space?.code) return [];
    return places.filter(p => p.kind === 'desk' && p.container_code === space.code);
  }

  function placeTitle(place) {
    if (!place) return '–';
    return place.name || place.category?.name || place.code || 'Без названия';
  }

  function deskOverlapsOthers(desk, x, y, w, h, rotation = 0) {
    return floorPlaces().some(p => {
      if (p.kind !== 'desk' || p.code === desk.code) return false;
      if (p.width == null || p.height == null) return false;
      return desksEffectiveOverlap(
        x, y, w, h, rotation,
        p.x, p.y, p.width, p.height, p.rotation || 0,
      );
    });
  }

  function locationOverlapsOthers(space, x, y, w, h) {
    return floorPlaces().some(p => {
      if (p.code === space.code) return false;
      if (p.container_code) return false;
      if (p.kind !== 'space' && p.kind !== 'room') return false;
      if (p.enclosed === false) return false;
      if (!rectsMeaningfulOverlap(x, y, w, h, p.x, p.y, p.width, p.height)) return false;
      if (rectContains(x, y, w, h, p.x, p.y, p.width, p.height)) return false;
      if (rectContains(p.x, p.y, p.width, p.height, x, y, w, h)) return false;
      return true;
    });
  }

  function findDeskParentAt(cx, cy, w, h) {
    const containers = floorPlaces()
      .filter(p => (p.kind === 'space' || p.kind === 'room') && allowsDesks(p))
      .sort((a, b) => (a.width * a.height) - (b.width * b.height));
    for (const p of containers) {
      if (cx >= p.x && cx <= p.x + p.width && cy >= p.y && cy <= p.y + p.height) {
        return p;
      }
    }
    return null;
  }

  function findBlockedDeskContainerAt(cx, cy) {
    return floorPlaces()
      .filter(p => (p.kind === 'space' || p.kind === 'room') && !allowsDesks(p))
      .find(p => cx >= p.x && cx <= p.x + p.width && cy >= p.y && cy <= p.y + p.height) || null;
  }

  function validateDeskInCorridor(x, y, w, h, floor, desk = null, rotation = 0) {
    const clamped = clampRectToFloorRotated(x, y, w, h, rotation, SVG_W, SVG_H, FLOOR_INSET);
    if (!clamped) return { ok: false, error: 'Стол не помещается на этаже' };
    let rx = clamped.x, ry = clamped.y;
    const eff = effectiveRectForRotation(rx, ry, w, h, rotation);
    const adj = adjustRectFromWalls(eff.x, eff.y, eff.w, eff.h, floor);
    const moved = applyEffectiveRectDelta(rx, ry, adj[0], adj[1], w, h, rotation);
    rx = moved.x;
    ry = moved.y;
    const eff2 = effectiveRectForRotation(rx, ry, w, h, rotation);
    if (rectOverlapsWalls(eff2.x, eff2.y, eff2.w, eff2.h, floor)) {
      return { ok: false, error: 'Нельзя разместить на стене' };
    }
    if (deskOverlapsOthers(desk || { code: '__new__' }, rx, ry, w, h, rotation)) {
      return { ok: false, error: 'Стол пересекается с другим столом' };
    }
    return { ok: true, x: Math.round(rx), y: Math.round(ry) };
  }

  function validateDeskInParent(parent, x, y, w, h, floor, desk = null, rotation = 0) {
    if (!parent || parent.width == null || parent.height == null) {
      return validateDeskInCorridor(x, y, w, h, floor, desk, rotation);
    }
    const eff = effectiveRectForRotation(x, y, w, h, rotation);
    if (!deskEffectiveRectInParent(parent, eff.x, eff.y, eff.w, eff.h, PARENT_INSET)) {
      const clamped = clampRectInParentRotated(x, y, w, h, rotation, parent, PARENT_INSET);
      if (!clamped) {
        return { ok: false, error: 'Стол должен оставаться внутри помещения' };
      }
      x = clamped.x;
      y = clamped.y;
    }
    const inset = PARENT_INSET;
    const effNow = effectiveRectForRotation(x, y, w, h, rotation);
    const minX = parent.x + inset;
    const minY = parent.y + inset;
    const maxX = parent.x + parent.width - inset - effNow.w;
    const maxY = parent.y + parent.height - inset - effNow.h;
    if (maxX < minX || maxY < minY) {
      return { ok: false, error: 'Стол не помещается в локацию' };
    }
    let effX = Math.max(minX, Math.min(effNow.x, maxX));
    let effY = Math.max(minY, Math.min(effNow.y, maxY));
    const wallBound = isWallBoundZone(parent);
    if (!wallBound) {
      [effX, effY] = adjustRectFromWalls(effX, effY, effNow.w, effNow.h, floor);
      effX = Math.max(minX, Math.min(effX, maxX));
      effY = Math.max(minY, Math.min(effY, maxY));
      if (rectOverlapsWalls(effX, effY, effNow.w, effNow.h, floor)) {
        return { ok: false, error: 'Нельзя разместить на стене' };
      }
    }
    const moved = applyEffectiveRectDelta(x, y, effX, effY, w, h, rotation);
    if (desk && deskOverlapsOthers(desk, moved.x, moved.y, w, h, rotation)) {
      return { ok: false, error: 'Стол пересекается с другим столом' };
    }
    return { ok: true, x: Math.round(moved.x), y: Math.round(moved.y) };
  }

  function resolveDeskDragPosition(nx, ny, w, h, floor, desk, lastX, lastY) {
    const rot = desk?.rotation || 0;
    const tryAt = (x, y) => {
      const effAt = effectiveRectForRotation(x, y, w, h, rot);
      const cx = effAt.x + effAt.w / 2, cy = effAt.y + effAt.h / 2;
      const blocked = findBlockedDeskContainerAt(cx, cy);
      if (blocked) {
        return { ok: false, error: deskBlockedMessage(blocked) };
      }
      const targetParent = findDeskParentAt(cx, cy, w, h);
      if (targetParent && allowsDesks(targetParent)) {
        return validateDeskInParent(targetParent, x, y, w, h, floor, desk, rot);
      }
      return validateDeskInCorridor(x, y, w, h, floor, desk, rot);
    };

    let check = tryAt(nx, ny);
    if (check.ok) return check;

    const tryX = tryAt(nx, lastY);
    const tryY = tryAt(lastX, ny);
    if (tryX.ok && tryY.ok) {
      const dX = Math.abs(nx - tryX.x) + Math.abs(ny - tryX.y);
      const dY = Math.abs(nx - tryY.x) + Math.abs(ny - tryY.y);
      return dX <= dY ? tryX : tryY;
    }
    if (tryX.ok) return tryX;
    if (tryY.ok) return tryY;

    const slid = slideRectOffDesks(
      nx, ny, w, h, rot, desk?.code, floorPlaces(), DESK_GAP,
    );
    const slideCheck = tryAt(slid.x, slid.y);
    if (slideCheck.ok) return slideCheck;

    const offsets = [8, 16, 24, 36, 48, 64, 84, 108];
    let best = null;
    const remember = candidate => {
      if (!candidate.ok) return;
      const dist = Math.abs(candidate.x - nx) + Math.abs(candidate.y - ny);
      if (!best || dist < best.dist) best = { ...candidate, dist };
    };
    for (const d of offsets) {
      [
        [nx - d, ny], [nx + d, ny], [nx, ny - d], [nx, ny + d],
        [lastX, ny - d], [lastX, ny + d], [nx - d, lastY], [nx + d, lastY],
        [nx - d, ny - d], [nx + d, ny - d], [nx - d, ny + d], [nx + d, ny + d],
      ].forEach(([x, y]) => remember(tryAt(x, y)));
      if (best && best.dist <= d * 1.5) return best;
    }
    if (best) return best;
    if (lastX != null && lastY != null) {
      const stick = tryAt(lastX, lastY);
      if (stick.ok) return stick;
      return { ok: true, x: lastX, y: lastY };
    }
    return check;
  }

  function floorPlaces() {
    return places.filter(p => Number(p.floor || 1) === currentFloor);
  }

  function isWallBoundZone(p) {
    if (!p) return false;
    if (p.source === 'walls') return true;
    return wallRooms.some(r => r.registered && r.place && r.place.code === p.code);
  }

  function floorWalls() {
    return walls.filter(w => Number(w.floor || 1) === currentFloor);
  }

  function floorDoors() {
    return doors.filter(d => Number(d.floor || 1) === currentFloor);
  }

  function pointOnWallSegment(px, py, w, tol = 14) {
    const dx = w.x2 - w.x1, dy = w.y2 - w.y1, len2 = dx * dx + dy * dy;
    if (len2 < 1) return null;
    const t = ((px - w.x1) * dx + (py - w.y1) * dy) / len2;
    if (t < 0.02 || t > 0.98) return null;
    const projX = w.x1 + t * dx, projY = w.y1 + t * dy;
    if (Math.hypot(px - projX, py - projY) > tol) return null;
    return t;
  }

  function doorPositionRange(w, doorWidth) {
    const dx = w.x2 - w.x1, dy = w.y2 - w.y1, len = Math.hypot(dx, dy);
    if (len < doorWidth + 16) return { min: 0.5, max: 0.5 };
    const hw = doorWidth / 2, margin = 12;
    let minP = (hw + margin) / len, maxP = 1 - (hw + margin) / len;
    const buf = (hw + margin) / len;
    floorWalls().forEach(ow => {
      if (ow.id === w.id) return;
      [[ow.x1, ow.y1], [ow.x2, ow.y2]].forEach(([px, py]) => {
        const t = pointOnWallSegment(px, py, w);
        if (t != null) { minP = Math.max(minP, t + buf); maxP = Math.min(maxP, t - buf); }
      });
    });
    if (minP > maxP) return { min: 0.5, max: 0.5 };
    return { min: minP, max: maxP };
  }

  function clampDoorPosition(w, position, doorWidth) {
    const { min, max } = doorPositionRange(w, doorWidth);
    return Math.max(min, Math.min(max, position));
  }

  function svgPoint(evt) {
    const svg = $('canvas');
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const ctm = svg.getScreenCTM().inverse();
    return pt.matrixTransform(ctm);
  }

  // --- Geometry ---
  function wallOverlapDepth(rx, ry, rw, rh, wall) {
    const { x1, y1, x2, y2 } = wall;
    if (Math.abs(x1 - x2) < 3) {
      const wx = (x1 + x2) / 2;
      if (ry + rh <= Math.min(y1, y2) || ry >= Math.max(y1, y2)) return 0;
      const wl = wx - WALL_HALF, wr = wx + WALL_HALF;
      return Math.max(0, Math.min(rx + rw, wr) - Math.max(rx, wl));
    }
    if (Math.abs(y1 - y2) < 3) {
      const wy = (y1 + y2) / 2;
      if (rx + rw <= Math.min(x1, x2) || rx >= Math.max(x1, x2)) return 0;
      const wt = wy - WALL_HALF, wb = wy + WALL_HALF;
      return Math.max(0, Math.min(ry + rh, wb) - Math.max(ry, wt));
    }
    return 0;
  }

  function rectOverlapsWalls(x, y, w, h, floor) {
    const rx = +x, ry = +y, rw = +w, rh = +h;
    for (const wall of floorWalls()) {
      if (wallOverlapDepth(rx, ry, rw, rh, wall) > WALL_PENETRATION) return true;
    }
    return false;
  }

  function adjustRectFromWalls(x, y, w, h, floor, maxPasses = 24) {
    let rx = +x, ry = +y;
    const maxX = SVG_W - FLOOR_INSET - w, maxY = SVG_H - FLOOR_INSET - h;
    rx = Math.max(FLOOR_INSET, Math.min(rx, maxX));
    ry = Math.max(FLOOR_INSET, Math.min(ry, maxY));
    for (let pass = 0; pass < maxPasses; pass++) {
      if (!rectOverlapsWalls(rx, ry, w, h, floor)) break;
      let moved = false;
      for (const wall of floorWalls()) {
        if (wallOverlapDepth(rx, ry, w, h, wall) <= WALL_PENETRATION) continue;
        const { x1, y1, x2, y2 } = wall;
        if (Math.abs(x1 - x2) < 3) {
          const wx = (x1 + x2) / 2;
          const wl = wx - WALL_HALF, wr = wx + WALL_HALF;
          if (rx + w / 2 < wx) rx = wl - w;
          else rx = wr;
          moved = true;
        } else if (Math.abs(y1 - y2) < 3) {
          const wy = (y1 + y2) / 2;
          const wt = wy - WALL_HALF, wb = wy + WALL_HALF;
          if (ry + h / 2 < wy) ry = wt - h;
          else ry = wb;
          moved = true;
        }
      }
      rx = Math.max(FLOOR_INSET, Math.min(rx, maxX));
      ry = Math.max(FLOOR_INSET, Math.min(ry, maxY));
      if (!moved) break;
    }
    return [Math.round(rx), Math.round(ry)];
  }

  function validateRect(x, y, w, h, floor, opts = {}) {
    let rx = +x, ry = +y;
    const maxX = SVG_W - FLOOR_INSET - w, maxY = SVG_H - FLOOR_INSET - h;
    rx = Math.max(FLOOR_INSET, Math.min(rx, maxX));
    ry = Math.max(FLOOR_INSET, Math.min(ry, maxY));
    if (!opts.allowWallContact && rectOverlapsWalls(rx, ry, w, h, floor)) {
      return { ok: false, error: 'Нельзя разместить на стене' };
    }
    if (opts.place && (opts.place.kind === 'space' || opts.place.kind === 'room')) {
      if (locationOverlapsOthers(opts.place, rx, ry, w, h)) {
        return { ok: false, error: 'Локация пересекается с другой' };
      }
    }
    return { ok: true, x: Math.round(rx), y: Math.round(ry) };
  }

  // --- Data ---
  async function loadLocationZones() {
    try {
      const data = await api('/api/admin/location-zones');
      locationZones = data.zones || [];
    } catch (e) {
      locationZones = [
        { id: 1, letter: 'A', name: 'Зона рабочих столов', kind: 'desk_zone', active: true },
        { id: 2, letter: 'B', name: 'Зона переговорных', kind: 'room_zone', active: true },
      ];
    }
    populateZoneSelect();
  }

  async function loadCategories() {
    const data = await api('/api/admin/categories');
    if (data.success) {
      categories = data.categories || [];
      renderDeskTemplates();
      populateCategorySelect();
    }
  }

  async function loadAll(silent) {
    try {
      const data = await api('/api/admin/editor/map?floor=' + currentFloor);
      places = data.places || [];
      walls = data.walls || [];
      doors = data.doors || [];
      wallRooms = data.rooms || [];
      render();
      if (!silent) {
        const desks = places.filter(p => p.kind === 'desk').length;
        const locs = places.filter(p => p.kind === 'space' || p.kind === 'room').length;
        const drafts = wallRooms.filter(r => !r.registered).length;
        toast(`${desks} столов · ${locs} локаций · ${drafts} черновиков`, 'success');
      }
    } catch (e) {
      toast('Не удалось загрузить', 'error');
    }
  }

  function populateZoneSelect() {
    const opts = locationZones.filter(z => z.active !== false).map(z =>
      `<option value="${z.id}">${z.letter} – ${z.name}</option>`
    ).join('');
    const sel = $('prop-location-zone');
    if (sel) sel.innerHTML = '<option value="">– зона –</option>' + opts;
    updateZoneHint();
    updateZoneFields();
  }

  function updateZoneHint() {
    const hint = $('prop-zone-hint');
    if (!hint) return;
    hint.textContent = locationZones
      .filter(z => z.active !== false)
      .map(z => `${z.letter} – ${z.name}`)
      .join(' · ');
  }

  function populateCategorySelect() {
    const sel = $('prop-category');
    if (!sel) return;
    sel.innerHTML = '<option value="">– категория –</option>' +
      categories.map(c => `<option value="${c.id}" data-kind="${c.kind}">${c.name}</option>`).join('');
  }

  function activeUniqueCategories(kind) {
    const seen = new Set();
    return categories.filter(c => c.active !== false && (!kind || c.kind === kind)).filter(c => {
      const key = [
        c.kind,
        String(c.name || '').trim().toLowerCase(),
        Number(c.capacity || 0),
        Number(c.width_m || 0).toFixed(2),
        Number(c.height_m || 0).toFixed(2),
      ].join('|');
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function placeFromRoom(room) {
    if (!room || !room.place) return null;
    return places.find(p => p.code === room.place.code || p.id === room.place.id) || null;
  }

  function roomFromPlace(p) {
    const meeting = isMeetingPlace(p);
    return {
      room_key: 'place-' + p.code,
      x: p.x, y: p.y,
      width: p.width, height: p.height,
      floor: p.floor || currentFloor,
      registered: true,
      place: {
        id: p.id,
        code: p.code,
        name: p.name,
        zone_type_id: p.zone_type_id,
        zone_type: p.zone_type,
        category: p.category,
        allows_desks: allowsDesks(p),
        is_meeting_room: meeting,
      },
    };
  }

  // --- Selection ---
  function selectLocation(room) {
    const registered = room.registered && room.place;
    selection = {
      type: 'location',
      room,
      place: registered ? placeFromRoom(room) : null,
      draft: !registered,
    };
    showPanel();
    render();
    loadVariantsForSelection();
  }

  function selectSpace(p) {
    selection = {
      type: 'location',
      room: roomFromPlace(p),
      place: p,
      draft: false,
    };
    showPanel();
    render();
    loadVariantsForSelection();
  }

  function getSelectedDesks() {
    if (!selection) return [];
    if (selection.type === 'desks') return selection.places || [];
    if (selection.type === 'desk' && selection.place) return [selection.place];
    return [];
  }

  function isDeskSelected(p) {
    return getSelectedDesks().some(d => d.code === p.code);
  }

  function selectDesk(place, additive = false) {
    if (additive) {
      let list = getSelectedDesks();
      const idx = list.findIndex(d => d.code === place.code);
      if (idx >= 0) list = list.filter((_, i) => i !== idx);
      else list = [...list, place];
      if (!list.length) {
        clearSelection();
        return;
      }
      if (list.length === 1) {
        selection = { type: 'desk', place: list[0] };
      } else {
        selection = { type: 'desks', places: list };
      }
    } else {
      selection = { type: 'desk', place };
    }
    showPanel();
    render();
    $('layout-helper').style.display = 'none';
  }

  function selectDoor(door) {
    selection = { type: 'door', door };
    showPanel();
    render();
    $('layout-helper').style.display = 'none';
  }

  function clearSelection() {
    selection = null;
    $('props-empty').style.display = 'block';
    $('props-form').style.display = 'none';
    $('layout-helper').style.display = 'none';
    render();
  }

  function showPanel() {
    $('props-empty').style.display = 'none';
    $('props-form').style.display = 'block';

    const isLoc = selection && selection.type === 'location';
    const isDesk = selection && selection.type === 'desk';
    const isDesks = selection && selection.type === 'desks';
    const isDoor = selection && selection.type === 'door';
    const p = isLoc ? selection.place : (isDesk ? selection.place : null);
    const room = isLoc ? selection.room : null;
    const draft = isLoc && selection.draft;
    const selectedDesks = getSelectedDesks();

    $('draft-banner').style.display = draft ? 'block' : 'none';
    $('btn-fix-location').style.display = draft ? 'block' : 'none';
    $('btn-save-location').style.display = draft ? 'none' : 'block';
    $('btn-delete-location').style.display = isLoc ? 'block' : 'none';
    const delLocBtn = $('btn-delete-location');
    if (delLocBtn) {
      delLocBtn.innerHTML = draft
        ? '<i class="fas fa-trash"></i> Убрать зону'
        : '<i class="fas fa-trash"></i> Удалить локацию';
    }
    $('desk-only-fields').style.display = isDesk ? 'block' : 'none';
    $('desk-multi-fields').style.display = isDesks ? 'block' : 'none';
    $('door-only-fields').style.display = isDoor ? 'block' : 'none';
    $('location-fields').style.display = isLoc ? 'block' : 'none';

    if (isLoc && room) {
      const wM = (room.width / SCALE).toFixed(2);
      const hM = (room.height / SCALE).toFixed(2);
      if (draft) {
        $('prop-title').textContent = 'Новая локация (черновик)';
        $('prop-code-hint').textContent = 'Зафиксируйте или уберите черновик кнопкой ниже';
      } else if (p) {
        $('prop-title').textContent = placeTitle(p) + ' (' + p.code + ')';
        $('prop-code-hint').textContent = 'Код: ' + p.code;
      }
      $('prop-size-m').value = wM + '×' + hM + ' м';
      $('prop-name').value = p ? p.name : '';
      if (p && p.zone_type_id) $('prop-location-zone').value = p.zone_type_id;
      else if (p && p.zone_type) $('prop-location-zone').value = p.zone_type.id;
      else if (locationZones.length) $('prop-location-zone').value = locationZones[0].id;
      if (p && p.category) $('prop-category').value = p.category.id;
      updateZoneFields();
      if (p && isMeetingPlace(p) && p.category) {
        $('prop-cap-display').value = p.category.capacity + ' мест (целиком)';
      } else if (p && allowsDesks(p)) {
        const seats = zoneSeatCapacity(p);
        $('prop-cap-display').value = seats ? seats + ' мест в зоне' : '–';
      } else {
        $('prop-cap-display').value = '–';
      }
      const wallHint = $('prop-wall-bound-hint');
      if (wallHint) {
        wallHint.style.display = (p && isWallBoundZone(p)) ? 'block' : 'none';
      }
    }

    if (isDesk && p) {
      $('prop-title').textContent = placeTitle(p) + ' (' + p.code + ')';
      $('prop-code-hint').textContent = p.container_code
        ? 'Стол ' + p.code + ' · помещение ' + p.container_code
        : 'Стол ' + p.code + ' · коридор · Ctrl+клик для выделения';
      $('prop-x').value = Math.round(p.x);
      $('prop-y').value = Math.round(p.y);
      $('prop-rotation').value = Math.round(p.rotation || 0);
    }

    if (isDesks && selectedDesks.length) {
      $('prop-title').textContent = 'Выделено столов: ' + selectedDesks.length;
      $('prop-code-hint').textContent = selectedDesks.map(d => d.code).join(', ');
    }

    if (isDoor && selection.door) {
      const d = selection.door;
      $('prop-title').textContent = 'Дверь #' + d.id;
      $('prop-code-hint').textContent = (d.width >= 150 ? '1.5 м (двустворчатая)' : '1 м (обычная)');
      $('door-width-edit').value = String(d.width || DOOR_W_1M);
    }
  }

  function isRoomZone(zone) {
    return isRoomZoneKind(zone);
  }

  function updateZoneFields() {
    const z = selectedZone();
    const { amenity, meeting } = zoneKindFlags(z);
    const catRow = $('prop-category-row');
    const catLabel = catRow?.querySelector('label');
    const deskHint = $('prop-desk-zone-hint');
    const enclosedRow = $('prop-enclosed-row');
    const amenityHint = $('prop-amenity-hint');
    if (catRow) catRow.style.display = meeting ? 'block' : 'none';
    if (catLabel) catLabel.textContent = meeting ? 'Тип переговорной' : 'Тип';
    if (deskHint) {
      deskHint.style.display = meeting || amenity ? 'none' : 'block';
      if (!meeting && !amenity && z) {
        deskHint.textContent = `Для «${z.name}» тип столов выбирается ниже в «Вариантах размещения».`;
      }
    }
    if (enclosedRow) enclosedRow.style.display = 'none';
    if (amenityHint) {
      amenityHint.style.display = amenity ? 'block' : 'none';
      if (amenity && z) {
        amenityHint.textContent = `${z.letter} – ${z.name} · только для карты, без бронирования`;
      }
    }
    filterCategoryByZone();
  }

  function filterCategoryByZone() {
    const z = zoneById($('prop-location-zone')?.value);
    const sel = $('prop-category');
    if (!sel || !categories.length) return;
    if (!isRoomZone(z)) return;
    const roomCats = activeUniqueCategories('room');
    const cur = sel.value;
    sel.innerHTML = roomCats.length
      ? roomCats.map(c => `<option value="${c.id}">${c.name}</option>`).join('')
      : '<option value="">Нет типов переговорных</option>';
    if (cur && sel.querySelector(`option[value="${cur}"]`)) sel.value = cur;
    else if (roomCats.length) sel.value = String(roomCats[0].id);
  }

  async function fetchRoomVariants(room, placeCode) {
    const zid = parseInt($('prop-location-zone')?.value || '', 10);
    const payload = {
      width: room.width,
      height: room.height,
      zone_type_id: zid || null,
    };
    if (placeCode) {
      const qs = zid ? `?zone_type_id=${zid}` : '';
      try {
        return await api('/api/admin/room/' + encodeURIComponent(placeCode) + '/variants' + qs);
      } catch (e) {
        if (!/не найдена/i.test(e.message || '')) throw e;
        toast('Локация на карте устарела — показываем предпросмотр по размеру комнаты', 'warning');
      }
    }
    return await api('/api/admin/room/draft-variants', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async function loadVariantsForSelection() {
    const helper = $('layout-helper');
    const metrics = $('helper-metrics');
    const options = $('helper-options');
    if (!selection || selection.type !== 'location') {
      variantsRequestSeq++;
      helper.style.display = 'none';
      return;
    }
    helper.style.display = 'block';
    $('layout-helper-title').textContent = 'Варианты размещения';
    const initialZone = selectedZone();
    const initialFlags = zoneKindFlags(initialZone);
    if (!selection.draft && selection.place && initialFlags.desk && desksInLocation(selection.place).length > 0) {
      variantsRequestSeq++;
      variants = [];
      variantMode = 'desks';
      const count = desksInLocation(selection.place).length;
      metrics.innerHTML = `${initialFlags.label} · уже размещено столов: ${count}`;
      options.innerHTML = '<div class="metric">Варианты предлагаются только для пустых помещений. Чтобы применить новую раскладку, сначала очистите или удалите текущие столы.</div>';
      return;
    }
    const requestId = ++variantsRequestSeq;
    const selectionKey = [
      selection.room?.room_key || '',
      selection.place?.code || '',
      $('prop-location-zone')?.value || '',
    ].join('|');
    metrics.innerHTML = 'Загрузка вариантов...';
    options.innerHTML = '';

    try {
      const room = selection.room;
      if (!room) return;
      const data = selection.draft || !selection.place
        ? await fetchRoomVariants(room, null)
        : await fetchRoomVariants(room, selection.place.code);
      const currentKey = [
        selection?.room?.room_key || '',
        selection?.place?.code || '',
        $('prop-location-zone')?.value || '',
      ].join('|');
      if (requestId !== variantsRequestSeq || currentKey !== selectionKey) {
        return;
      }
      variants = data.variants || [];
      variantMode = data.mode || 'desks';
      const roomW = room?.width ?? selection.place?.width ?? 0;
      const roomH = room?.height ?? selection.place?.height ?? 0;
      const rw = (roomW / SCALE).toFixed(1);
      const rh = (roomH / SCALE).toFixed(1);
      const { z, amenity, meeting, label } = zoneKindFlags();

      if (meeting && variants.length) {
        const fittingIds = new Set(variants.filter(v => v.fits && v.category_id).map(v => String(v.category_id)));
        const sel = $('prop-category');
        const roomCats = activeUniqueCategories('room');
        if (sel && roomCats.length) {
          const cur = sel.value;
          sel.innerHTML = roomCats.map(c =>
            `<option value="${c.id}"${fittingIds.has(String(c.id)) ? '' : ' disabled'}>${c.name}${fittingIds.has(String(c.id)) ? '' : ' — не помещается'}</option>`
          ).join('');
          const currentOption = cur ? sel.querySelector(`option[value="${cur}"]`) : null;
          if (currentOption && !currentOption.disabled) sel.value = cur;
          else {
            const firstFit = roomCats.find(c => fittingIds.has(String(c.id)));
            if (firstFit) sel.value = String(firstFit.id);
          }
          const nameInput = $('prop-name');
          if (nameInput && !nameInput.value.trim()) {
            const selected = roomCats.find(c => String(c.id) === sel.value);
            nameInput.value = selected?.name || '';
          }
        }
      }
      metrics.innerHTML = amenity
        ? `${label} · ${rw}×${rh} м – зафиксируйте локацию`
        : meeting
          ? `${label} · ${rw}×${rh} м – выберите тип комнаты`
          : `${label} · ${rw}×${rh} м – подберите тип столов и сетку`;
      renderVariantCards(options);
    } catch (e) {
      if (requestId !== variantsRequestSeq) return;
      metrics.innerHTML = 'Ошибка загрузки вариантов';
      options.innerHTML = `<div class="metric">${escapeHtml(friendlyError(e, 'Не удалось загрузить варианты'))}</div>`;
      toast(e.message || 'Не удалось загрузить варианты', 'error');
    }
  }

  function renderVariantCards(container) {
    container.innerHTML = '';
    const { amenity, label } = zoneKindFlags();
    if (amenity || variantMode === 'amenity') {
      container.innerHTML = `<div class="metric">Нажмите «Зафиксировать локацию» – ${label}, без столов и бронирования</div>`;
      return;
    }
    if (!variants.length) {
      container.innerHTML = '<div class="metric">Нет подходящих вариантов</div>';
      return;
    }
    variants.forEach((v, idx) => {
      const card = document.createElement('div');
      card.className = 'suggestion-card' + (v.fits ? ' fits' : '');
      const disabled = v.variant_type === 'meeting' && !v.fits;
      card.innerHTML = `<strong>${v.title}</strong><span>${v.description}</span>`;
      const btn = document.createElement('button');
      btn.textContent = v.variant_type === 'meeting' ? 'Назначить' : 'Применить';
      btn.disabled = disabled;
      if (disabled) btn.style.opacity = '0.5';
      btn.onclick = () => applyVariant(idx);
      card.appendChild(btn);
      container.appendChild(card);
    });
  }

  async function syncLocationZoneFromForm(place) {
    const zid = $('prop-location-zone')?.value;
    if (!zid || !place?.id) return place;
    const z = zoneById(zid);
    if (!isRoomZone(z) || isAmenityZone(z)) return place;
    const res = await api('/api/admin/place/' + place.id + '/location-zone', {
      method: 'PUT',
      body: JSON.stringify({ zone_type_id: parseInt(zid, 10), floor: currentFloor }),
    });
    if (res.place) {
      selection.place = res.place;
      if (res.renamed && res.old_code) {
        toast(res.message || ('Код: ' + res.old_code + ' → ' + res.place.code), 'success');
      }
      return res.place;
    }
    return place;
  }

  let _applyVariantBusy = false;
  async function applyVariant(idx) {
    const v = variants[idx];
    if (!v) return;
    if (_applyVariantBusy) {
      toast('Подождите — предыдущее размещение ещё выполняется', 'warning');
      return;
    }
    if (selection.draft) {
      await fixLocation(true, v);
      return;
    }
    if (!selection.place) return;
    _applyVariantBusy = true;
    try {
      let place = selection.place;
      if (v.variant_type === 'meeting') {
        place = await syncLocationZoneFromForm(place);
      }
      const data = await api('/api/admin/room/' + encodeURIComponent(place.code) + '/variants', {
        method: 'POST',
        body: JSON.stringify({ ...v, clear_existing: true }),
      });
      const n = data.result?.created ?? 0;
      if (v.variant_type === 'desks' && n === 0) {
        toast('Столы не разместились — проверьте размер помещения', 'error');
      } else if (v.variant_type === 'desks') {
        toast(`Размещено столов: ${n}`, 'success');
      } else {
        toast('Вариант применён', 'success');
      }
      await loadAll(true);
      const code = selection.place?.code;
      const p = places.find(x => x.code === code);
      const room = wallRooms.find(r => r.place && r.place.code === code);
      if (room) selectLocation(room);
      else if (p) {
        const wr = wallRooms.find(r =>
          Math.abs(r.x - p.x) < 20 && Math.abs(r.y - p.y) < 20
        );
        if (wr) selectLocation(wr);
      }
    } catch (e) {
      toast(e.message || 'Ошибка', 'error');
    } finally {
      _applyVariantBusy = false;
    }
  }

  async function fixLocation(andApplyVariant, variant) {
    const room = selection && selection.room;
    if (!room) return;
    const zid = parseInt($('prop-location-zone').value, 10);
    const z = zoneById(zid);
    let name = $('prop-name').value.trim();
    if (!name && z) name = z.name || ('Зона ' + z.letter);
    const meeting = isRoomZone(z);
    const amenity = isAmenityZone(z);
    const catId = meeting ? parseInt($('prop-category').value, 10) : null;
    const enclosed = amenity ? false : true;
    if (!zid || !name) {
      toast('Укажите зону и название', 'error');
      return;
    }
    if (meeting && !catId) {
      toast('Выберите тип переговорной', 'error');
      return;
    }
    const check = validateRect(room.x, room.y, room.width, room.height, currentFloor, {
      allowWallContact: true,
      place: { code: '__new__', kind: meeting ? 'room' : 'space' },
    });
    if (!check.ok) { toast(check.error, 'error'); return; }

    try {
      const payload = {
          name, zone_type_id: zid,
          x: room.x, y: room.y,
          width: room.width, height: room.height,
          floor: currentFloor, enclosed,
          source: 'walls',
      };
      if (catId) payload.category_id = catId;
      const data = await api('/api/admin/room/register', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      toast('Локация зарегистрирована: ' + data.place.code, 'success');
      await loadAll(true);
      const code = data.place.code;
      const wr = wallRooms.find(r => r.place && r.place.code === code);
      if (wr) {
        selectLocation(wr);
        if (andApplyVariant && variant) {
          variants = [variant];
          await applyVariant(0);
        }
      }
    } catch (e) {
      toast(e.message || 'Ошибка регистрации', 'error');
    }
  }

  async function saveLocation() {
    if (!selection || !selection.place) return;
    let p = selection.place;
    const zid = $('prop-location-zone').value;
    const z = zoneById(zid);
    const catId = $('prop-category').value;
    const name = $('prop-name').value.trim();

    try {
      await api('/api/admin/place/' + p.id + '/layout', {
        method: 'PUT',
        body: JSON.stringify({ name: name || p.name, enclosed: true }),
      });
      if (zid) {
        const zRes = await api('/api/admin/place/' + p.id + '/location-zone', {
          method: 'PUT',
          body: JSON.stringify({ zone_type_id: parseInt(zid, 10), floor: currentFloor }),
        });
        if (zRes.place) {
          p = zRes.place;
          selection.place = p;
          const wr = wallRooms.find(r =>
            r.place && (r.place.code === p.code || r.place.code === zRes.old_code)
          );
          if (wr) wr.place = p;
          $('prop-title').textContent = placeTitle(p) + ' (' + p.code + ')';
          $('prop-code-hint').textContent = 'Код: ' + p.code;
        }
        if (zRes.renamed) toast(zRes.message, 'success');
      }
      if (isRoomZone(z) && !isAmenityZone(z) && catId) {
        await api('/api/admin/place/' + p.id + '/category', {
          method: 'PUT',
          body: JSON.stringify({ category_id: parseInt(catId, 10) }),
        });
      }
      if (isRoomZone(z) && !isAmenityZone(z) && catId) {
        const selectedName = $('prop-category')?.selectedOptions?.[0]?.textContent?.trim();
        if (selectedName) {
          await api('/api/admin/place/' + p.id + '/layout', {
            method: 'PUT',
            body: JSON.stringify({ name: selectedName, enclosed: true }),
          });
        }
        await api('/api/admin/room/' + encodeURIComponent(p.code) + '/variants', {
          method: 'POST',
          body: JSON.stringify({
            variant_type: 'meeting',
            category_id: parseInt(catId, 10),
            clear_existing: true,
          }),
        });
      }
      toast('Сохранено', 'success');
      await loadAll(true);
      const wr = wallRooms.find(r => r.place && r.place.code === p.code);
      if (wr) selectLocation(wr);
    } catch (e) {
      toast(e.message || 'Ошибка', 'error');
    }
  }

  function dismissRoomPayload(room, code) {
    const payload = {
      x: Math.round(room.x),
      y: Math.round(room.y),
      width: Math.round(room.width),
      height: Math.round(room.height),
      floor: room.floor || currentFloor,
      room_key: room.room_key,
    };
    if (code) payload.code = code;
    return payload;
  }

  async function dismissWallRoom(room, code) {
    const data = await api('/api/admin/room/dismiss-draft', {
      method: 'POST',
      body: JSON.stringify(dismissRoomPayload(room, code)),
    });
    return data;
  }

  async function deleteLocation() {
    if (!selection || selection.type !== 'location') return;
    const room = selection.room;
    const place = selection.place;

    if (selection.draft && room) {
      askConfirm(
        'Убрать эту зону с карты? Общие стены с соседней комнатой останутся.',
        async () => {
          try {
            const data = await dismissWallRoom(room);
            clearSelection();
            await loadAll(true);
            toast(data.message || 'Зона убрана', 'success');
          } catch (e) {
            toast(e.message || 'Ошибка', 'error');
          }
        },
        'Убрать',
      );
      return;
    }

    if (!place || !place.code) return;
    const label = place.name || place.code;
    const wallRoom = wallRooms.find(r => r.place && r.place.code === place.code)
      || (isWallBoundZone(place) && room && room.room_key && !String(room.room_key).startsWith('place-')
        ? room : null);
    askConfirm('Удалить локацию «' + label + '»?', async () => {
      try {
        if (place.id) {
          await api('/api/admin/place/' + place.id, { method: 'DELETE' });
        } else {
          await api('/api/admin/place-by-code/' + encodeURIComponent(place.code), {
            method: 'DELETE',
          });
        }
        if (wallRoom) {
          await dismissWallRoom(wallRoom, place.code);
        }
        clearSelection();
        await loadAll(true);
        toast('Локация «' + label + '» удалена', 'success');
      } catch (e) {
        toast(e.message || 'Ошибка удаления', 'error');
      }
    });
  }

  // --- Render ---
  function roomStyle(room) {
    const selected = selection && selection.type === 'location' &&
      selection.room && selection.room.room_key === room.room_key;
    const registered = room.registered;
    const isMeeting = room.place && isMeetingPlace(room.place);
    const isAmenity = room.place && isAmenityPlace(room.place);
    let fill = 'rgba(148,163,184,0.12)';
    let stroke = '#94a3b8';
    if (registered) {
      if (isAmenity) {
        fill = 'rgba(148,163,184,0.18)';
        stroke = '#64748b';
      } else if (isMeeting) {
        fill = 'rgba(99,102,241,0.15)';
        stroke = '#6366f1';
      } else {
        fill = 'rgba(34,197,94,0.12)';
        stroke = '#22c55e';
      }
    }
    if (selected) { stroke = '#f59e0b'; }
    return { fill, stroke, dash: registered ? 'none' : '8,4', sw: selected ? 4 : 2 };
  }

  function renderRooms() {
    const layer = $('rooms-layer');
    if (!layer) return;
    layer.innerHTML = '';
    wallRooms.filter(room => !room.registered).forEach(room => {
      const st = roomStyle(room);
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', room.x);
      rect.setAttribute('y', room.y);
      rect.setAttribute('width', room.width);
      rect.setAttribute('height', room.height);
      rect.setAttribute('fill', st.fill);
      rect.setAttribute('stroke', st.stroke);
      rect.setAttribute('stroke-width', st.sw);
      if (st.dash !== 'none') rect.setAttribute('stroke-dasharray', st.dash);
      rect.style.cursor = 'pointer';
      rect.addEventListener('mousedown', e => {
        e.stopPropagation();
        if (!wallMode && !doorMode) selectLocation(room);
      });
      layer.appendChild(rect);

      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', room.x + room.width / 2);
      label.setAttribute('y', room.y + 16);
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('font-size', 11);
      label.setAttribute('fill', '#475569');
      label.setAttribute('pointer-events', 'none');
      label.textContent = room.registered
        ? (placeTitle(room.place) + ' (' + room.place.code + ')')
        : 'Комната · не зарегистрирована';
      layer.appendChild(label);
    });
  }

  function renderSpaces() {
    const layer = $('spaces-layer');
    if (!layer) return;
    layer.innerHTML = '';
    floorPlaces().filter(p => p.kind === 'space' || p.kind === 'room').forEach(p => {
      const selected = selection && selection.type === 'location' &&
        selection.place && selection.place.code === p.code;
      const meeting = isMeetingPlace(p);
      const amenity = isAmenityPlace(p);
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', p.x);
      rect.setAttribute('y', p.y);
      rect.setAttribute('width', p.width);
      rect.setAttribute('height', p.height);
      let fill = 'rgba(34,197,94,0.1)';
      let stroke = '#22c55e';
      if (amenity) { fill = '#e8edf2'; stroke = '#64748b'; }
      else if (meeting) { fill = 'rgba(99,102,241,0.14)'; stroke = '#6366f1'; }
      rect.setAttribute('fill', fill);
      rect.setAttribute('stroke', selected ? '#f59e0b' : stroke);
      rect.setAttribute('stroke-width', selected ? 4 : 2);
      rect.style.cursor = 'pointer';
      rect.addEventListener('mousedown', e => {
        e.stopPropagation();
        if (wallMode || doorMode) return;
        selectSpace(p);
      });
      g.appendChild(rect);
      const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lbl.setAttribute('x', p.x + p.width / 2);
      lbl.setAttribute('y', p.y + 22);
      lbl.setAttribute('text-anchor', 'middle');
      lbl.setAttribute('font-size', 22);
      lbl.setAttribute('font-weight', '600');
      lbl.setAttribute('fill', amenity ? '#111827' : (meeting ? '#4338ca' : '#15803d'));
      lbl.setAttribute('pointer-events', 'none');
      lbl.setAttribute('class', 'map-place-label');
      lbl.setAttribute('style', 'user-select:none;-webkit-user-select:none;pointer-events:none;');
      lbl.textContent = placeTitle(p) + ' (' + p.code + ')';
      g.appendChild(lbl);
      layer.appendChild(g);
    });
  }

  function renderDesks() {
    const layer = $('desks-layer');
    if (!layer) return;
    layer.innerHTML = '';
    floorPlaces().filter(p => p.kind === 'desk' && p.width != null && p.height != null).forEach(p => {
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      const rot = p.rotation || 0;
      const cx = p.x + p.width / 2, cy = p.y + p.height / 2;
      if (rot) g.setAttribute('transform', `rotate(${rot} ${cx} ${cy})`);
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', p.x); rect.setAttribute('y', p.y);
      rect.setAttribute('width', p.width); rect.setAttribute('height', p.height);
      rect.setAttribute('rx', 4);
      rect.setAttribute('fill', p.visual_only ? 'rgba(34,197,94,0.2)' : 'rgba(34,197,94,0.35)');
      rect.setAttribute('stroke', isDeskSelected(p) ? '#f59e0b' : '#16a34a');
      rect.setAttribute('stroke-width', 3);
      rect.style.cursor = 'move';
      rect.addEventListener('mousedown', e => { e.stopPropagation(); startDeskDrag(e, p); });
      g.appendChild(rect);
      const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lbl.setAttribute('x', p.x + p.width / 2);
      lbl.setAttribute('y', p.y + p.height / 2 + 4);
      lbl.setAttribute('text-anchor', 'middle');
      lbl.setAttribute('font-size', 10);
      lbl.setAttribute('fill', '#14532d');
      lbl.setAttribute('pointer-events', 'none');
      lbl.textContent = p.code;
      g.appendChild(lbl);
      layer.appendChild(g);
    });
  }

  function renderWalls() {
    const layer = $('walls-layer');
    layer.innerHTML = '';
    floorWalls().forEach(w => {
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      ln.setAttribute('x1', w.x1); ln.setAttribute('y1', w.y1);
      ln.setAttribute('x2', w.x2); ln.setAttribute('y2', w.y2);
      ln.classList.add('wall-line');
      if (w.protected) ln.classList.add('protected');
      ln.dataset.wallId = w.id;
      ln.addEventListener('mousedown', e => {
        e.stopPropagation();
        if (doorMode) { addDoorAtWall(w, svgPoint(e)); return; }
        if (wallMoveMode && !w.protected) { startWallDrag(e, w); return; }
        if (wallMode) { handleWallModeClick(svgPoint(e)); return; }
      });
      ln.addEventListener('click', e => {
        e.stopPropagation();
        if (doorMode || wallMoveMode || wallMode) return;
        if (w.protected) return;
        askConfirm('Удалить эту стену?', () => deleteWall(w.id));
      });
      layer.appendChild(ln);
    });
  }

  function renderDoors() {
    const layer = $('doors-layer');
    layer.innerHTML = '';
    floorDoors().forEach(d => {
      const w = floorWalls().find(x => x.id === d.wall_id);
      if (!w) {
        const orphan = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        orphan.classList.add('door-orphan');
        const cx = 200 + (d.id % 5) * 80, cy = 200 + Math.floor(d.id / 5) * 60;
        const mark = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        mark.setAttribute('cx', cx);
        mark.setAttribute('cy', cy);
        mark.setAttribute('r', 14);
        mark.setAttribute('fill', '#fef3c7');
        mark.setAttribute('stroke', '#d97706');
        mark.setAttribute('stroke-width', 2);
        orphan.appendChild(mark);
        const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        lbl.setAttribute('x', cx);
        lbl.setAttribute('y', cy + 28);
        lbl.setAttribute('text-anchor', 'middle');
        lbl.setAttribute('fill', '#b45309');
        lbl.setAttribute('font-size', '10');
        lbl.textContent = 'Дверь #' + d.id + ' (нет стены)';
        orphan.appendChild(lbl);
        layer.appendChild(orphan);
        return;
      }
      const dx = w.x2 - w.x1, dy = w.y2 - w.y1, len = Math.hypot(dx, dy);
      if (len < 1) return;
      const ux = dx / len, uy = dy / len;
      const mx = w.x1 + dx * d.position, my = w.y1 + dy * d.position;
      const hw = (d.width || DOOR_W_1M) / 2;
      const sx = mx - ux * hw, sy = my - uy * hw;
      const ex = mx + ux * hw, ey = my + uy * hw;
      const px = -uy, py = ux;
      const sel = selection && selection.type === 'door' && selection.door && selection.door.id === d.id;
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.classList.add('door-group');
      if (sel) g.classList.add('selected');

      const gap = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      gap.setAttribute('x1', sx); gap.setAttribute('y1', sy);
      gap.setAttribute('x2', ex); gap.setAttribute('y2', ey);
      gap.classList.add('door-gap');
      g.appendChild(gap);

      const frameL = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      frameL.setAttribute('x1', sx - px * 4); frameL.setAttribute('y1', sy - py * 4);
      frameL.setAttribute('x2', sx + px * 4); frameL.setAttribute('y2', sy + py * 4);
      frameL.classList.add('door-frame');
      g.appendChild(frameL);
      const frameR = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      frameR.setAttribute('x1', ex - px * 4); frameR.setAttribute('y1', ey - py * 4);
      frameR.setAttribute('x2', ex + px * 4); frameR.setAttribute('y2', ey + py * 4);
      frameR.classList.add('door-frame');
      g.appendChild(frameR);

      const hit = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      hit.setAttribute('x1', sx); hit.setAttribute('y1', sy);
      hit.setAttribute('x2', ex); hit.setAttribute('y2', ey);
      hit.classList.add('door-hit');
      if (sel) hit.classList.add('selected');
      hit.addEventListener('mousedown', e => {
        e.stopPropagation();
        if (doorMode) return;
        selectDoor(d);
        startDoorDrag(e, d, w);
      });
      g.appendChild(hit);
      layer.appendChild(g);
    });
  }

  function renderLocationsList() {
    const box = $('locations-list');
    if (!box) return;
    const items = [];
    floorPlaces().filter(p => p.kind === 'space' || p.kind === 'room').forEach(p => {
      items.push({
        key: 'place-' + p.code,
        title: placeTitle(p) + ' (' + p.code + ')',
        sub: placeZoneSub(p),
        onClick: () => selectSpace(p),
      });
    });
    wallRooms.filter(r => !r.registered).forEach(r => {
      items.push({
        key: r.room_key,
        title: 'Комната (черновик)',
        sub: 'По стенам · не зарегистрирована',
        onClick: () => selectLocation(r),
      });
    });
    if (!items.length) {
      box.innerHTML = '<div style="color:#64748b;padding:8px;">Нет локаций на этаже</div>';
      return;
    }
    box.innerHTML = items.map(it => {
      const sel = selection && selection.room && selection.room.room_key === it.key;
      return `<button type="button" data-key="${it.key}" style="display:block;width:100%;text-align:left;margin-bottom:6px;padding:8px;border-radius:6px;border:1px solid ${sel ? '#f59e0b' : '#475569'};background:${sel ? '#422006' : '#334155'};color:#e2e8f0;cursor:pointer;font-size:12px;">
        <strong>${it.title}</strong><br><span style="color:#94a3b8;font-size:11px;">${it.sub}</span>
      </button>`;
    }).join('');
    box.querySelectorAll('button[data-key]').forEach(btn => {
      const it = items.find(x => x.key === btn.dataset.key);
      if (it) btn.onclick = it.onClick;
    });
  }

  function renderDeskTemplates() {
    const box = $('templates-list');
    if (!box) return;
    const desks = activeUniqueCategories('desk');
    const loc = selection && selection.place;
    const deskHint = loc && isMeetingPlace(loc)
      ? '<p style="font-size:11px;color:#a5b4fc;">Мебель переговорной (бронь только целиком)</p>'
      : (loc && !allowsDesks(loc)
        ? `<p style="font-size:11px;color:#fcd34d;">В «${escapeHtml(placeZoneSub(loc))}» столы не размещаются.</p>`
        : '<p style="font-size:11px;color:#86efac;">Перетащите стол в закрытое помещение или в коридор.</p>');
    const html = '<h3>Столы</h3>' + deskHint + desks.map(c =>
      `<div class="tpl" data-kind="desk" data-cat-id="${c.id}" data-w="${c.width_px}" data-h="${c.height_px}" data-name="${c.name}">
        <div class="tpl-name">${c.name}</div><div class="tpl-meta">${c.width_m}×${c.height_m} м</div>
      </div>`
    ).join('');
    box.innerHTML = html;
    if (!_tplBound) {
      box.addEventListener('mousedown', e => {
        const card = e.target.closest('.tpl');
        if (!card) return;
        handleDeskDrag(e, card);
      });
      _tplBound = true;
    }
  }

  function updateEditLayerPointerEvents() {
    const block = wallMode || doorMode || wallMoveMode;
    ['rooms-layer', 'spaces-layer', 'desks-layer'].forEach(id => {
      const el = $(id);
      if (el) el.style.pointerEvents = block ? 'none' : 'all';
    });
    document.body.classList.toggle('wall-move-mode', wallMoveMode);
  }

  function render() {
    renderWalls();
    renderRooms();
    renderSpaces();
    renderDesks();
    renderDoors();
    updateEditLayerPointerEvents();
    renderLocationsList();
    renderDeskTemplates();
  }

  // --- Desk drag template ---
  function handleDeskDrag(e, card) {
    e.preventDefault();
    const w = +card.dataset.w, h = +card.dataset.h, catId = +card.dataset.catId;
    const ghost = card.cloneNode(true);
    ghost.style.cssText = 'position:fixed;pointer-events:none;opacity:.7;z-index:9999';
    document.body.appendChild(ghost);
    function mv(ev) { ghost.style.left = ev.clientX + 'px'; ghost.style.top = ev.clientY + 'px'; }
    function up(ev) {
      document.removeEventListener('mousemove', mv);
      document.removeEventListener('mouseup', up);
      ghost.remove();
      const svg = $('canvas').getBoundingClientRect();
      if (ev.clientX < svg.left || ev.clientX > svg.right || ev.clientY < svg.top || ev.clientY > svg.bottom) return;
      const pt = svgPoint(ev);
      const selectedParent = (selection && selection.type === 'location' && !selection.draft)
        ? selection.place : null;
      let parent = selectedParent;
      if (!parent || !allowsDesks(parent)) {
        parent = findDeskParentAt(pt.x, pt.y, w, h);
      }
      if (parent && allowsDesks(parent)) {
        const check = validateDeskInParent(
          parent, pt.x - w / 2, pt.y - h / 2, w, h, currentFloor,
          { code: '__new__', container_code: parent.code },
        );
        if (!check.ok) { toast(check.error, 'error'); return; }
        createDesk(parent, check.x, check.y, w, h, catId, card.dataset.name);
        return;
      }
      const blockedParent = parent || selectedParent || findBlockedDeskContainerAt(pt.x, pt.y);
      if (blockedParent && (blockedParent.kind === 'space' || blockedParent.kind === 'room') && !allowsDesks(blockedParent)) {
        toast(deskBlockedMessage(blockedParent), 'error');
        return;
      }
      const corridorCheck = validateDeskInCorridor(
        pt.x - w / 2, pt.y - h / 2, w, h, currentFloor,
      );
      if (!corridorCheck.ok) { toast(corridorCheck.error, 'error'); return; }
      createDeskOpen(corridorCheck.x, corridorCheck.y, w, h, catId, card.dataset.name);
    }
    document.addEventListener('mousemove', mv);
    document.addEventListener('mouseup', up);
  }

  async function createDesk(parent, x, y, w, h, catId, name) {
    if (_createBusy) return;
    if (!allowsDesks(parent)) {
      toast(deskBlockedMessage(parent), 'error');
      return;
    }
    _createBusy = true;
    try {
      await api('/api/admin/place/create', {
        method: 'POST',
        body: JSON.stringify({
          name: name || 'Стол',
          kind: 'desk',
          container_code: parent.code,
          location_code: parent.location_code || parent.location,
          x, y, width: w, height: h,
          floor: currentFloor,
          category_id: catId,
        }),
      });
      toast('Стол добавлен', 'success');
      await loadAll(true);
      const wr = wallRooms.find(r => r.place && r.place.code === parent.code);
      if (wr) selectLocation(wr);
    } catch (e) {
      toast(e.message || 'Ошибка', 'error');
    } finally {
      _createBusy = false;
    }
  }

  async function createDeskOpen(x, y, w, h, catId, name) {
    if (_createBusy) return;
    const blockedParent = findBlockedDeskContainerAt(x + w / 2, y + h / 2);
    if (blockedParent) {
      toast(deskBlockedMessage(blockedParent), 'error');
      return;
    }
    _createBusy = true;
    try {
      const selectedZone = zoneById($('prop-location-zone')?.value);
      const z = (selectedZone && isDeskZone(selectedZone))
        ? selectedZone
        : (locationZones.find(zn => isDeskZone(zn)) || locationZones[0]);
      const locCode = z ? `${currentFloor}${z.letter}` : `${currentFloor}A`;
      const data = await api('/api/admin/place/create', {
        method: 'POST',
        body: JSON.stringify({
          name: name || 'Стол',
          kind: 'desk',
          location_code: locCode,
          x, y, width: w, height: h,
          floor: currentFloor,
          category_id: catId,
        }),
      });
      const msg = data.parent
        ? `Стол добавлен в «${data.parent.name}»`
        : (data.message || 'Стол добавлен в коридор');
      toast(msg, 'success');
      await loadAll(true);
      if (data.container_code) {
        const p = places.find(pl => pl.code === data.container_code);
        if (p) selectSpace(p);
      }
    } catch (e) {
      toast(e.message || 'Ошибка', 'error');
    } finally {
      _createBusy = false;
    }
  }

  function startDeskDrag(evt, p) {
    evt.preventDefault();
    evt.stopPropagation();
    const ox = p.x, oy = p.y;
    const start = svgPoint(evt);
    const dragG = evt.target.closest('g');
    let lastX = ox, lastY = oy;
    let moved = false;
    function mv(e) {
      moved = true;
      const cur = svgPoint(e);
      const nx = ox + cur.x - start.x, ny = oy + cur.y - start.y;
      if (p.width == null || p.height == null) return;
      const check = resolveDeskDragPosition(
        nx, ny, p.width, p.height, currentFloor, p, lastX, lastY,
      );
      if (!check.ok) {
        if (check.x === lastX && check.y === lastY) return;
        toastLimited('desk-drag-limit', check.error || 'Стол нельзя поставить в это место', 'warning');
        return;
      }
      p.x = check.x;
      p.y = check.y;
      lastX = p.x;
      lastY = p.y;
      if (dragG) {
        const rect = dragG.querySelector('rect');
        const lbl = dragG.querySelector('text');
        const rot = p.rotation || 0;
        const cx = p.x + p.width / 2, cy = p.y + p.height / 2;
        if (rot) dragG.setAttribute('transform', `rotate(${rot} ${cx} ${cy})`);
        else dragG.removeAttribute('transform');
        if (rect) { rect.setAttribute('x', p.x); rect.setAttribute('y', p.y); }
        if (lbl) {
          lbl.setAttribute('x', p.x + p.width / 2);
          lbl.setAttribute('y', p.y + p.height / 2 + 4);
        }
      }
    }
    function up(e) {
      document.removeEventListener('mousemove', mv);
      document.removeEventListener('mouseup', up);
      if (!moved) {
        selectDesk(p, e.ctrlKey || e.metaKey);
        return;
      }
      api('/api/admin/place/move', {
        method: 'POST',
        body: JSON.stringify({ code: p.code, x: p.x, y: p.y, floor: currentFloor }),
      }).catch(err => {
        p.x = ox;
        p.y = oy;
        render();
        toast(err.message || 'Стол пересекается с другим или не помещается', 'error');
      });
      selectDesk(p);
    }
    document.addEventListener('mousemove', mv);
    document.addEventListener('mouseup', up);
  }

  async function saveDesk() {
    if (!selection || selection.type !== 'desk' || !selection.place) return;
    const p = selection.place;
    const rot = parseInt($('prop-rotation').value, 10) || 0;
    const parent = deskParent(p);
    const check = parent
      ? validateDeskInParent(parent, p.x, p.y, p.width, p.height, currentFloor, p, rot)
      : validateDeskInCorridor(p.x, p.y, p.width, p.height, currentFloor, p, rot);
    if (!check.ok) {
      toast(check.error || 'Стол не помещается с таким поворотом', 'error');
      return;
    }
    try {
      if (check.x !== p.x || check.y !== p.y) {
        await api('/api/admin/place/move', {
          method: 'POST',
          body: JSON.stringify({ code: p.code, x: check.x, y: check.y, floor: currentFloor }),
        });
        p.x = check.x;
        p.y = check.y;
      }
      await api('/api/admin/place/rotate', {
        method: 'POST',
        body: JSON.stringify({ code: p.code, rotation: rot }),
      });
      p.rotation = rot;
      toast('Стол сохранён', 'success');
      render();
    } catch (e) { toast(e.message || 'Ошибка', 'error'); }
  }

  async function rotateDesk(delta) {
    if (!selection || selection.type !== 'desk') return;
    const inp = $('prop-rotation');
    inp.value = ((parseInt(inp.value, 10) || 0) + delta + 360) % 360;
    await saveDesk();
  }

  async function deleteDesk() {
    if (!selection || !selection.place) return;
    const p = selection.place;
    askConfirm('Удалить стол «' + p.code + '»?', async () => {
      try {
        if (p.id) {
          await api('/api/admin/place/' + p.id, { method: 'DELETE' });
        } else {
          await api('/api/admin/place-by-code/' + encodeURIComponent(p.code), { method: 'DELETE' });
        }
        clearSelection();
        await loadAll(true);
        toast('Стол удалён', 'success');
      } catch (e) { toast(e.message || 'Ошибка удаления', 'error'); }
    }, 'Удалить', { title: 'Удаление стола', icon: 'trash' });
  }

  function startWallDrag(evt, w) {
    evt.preventDefault();
    const start = svgPoint(evt);
    const isVert = Math.abs(w.x1 - w.x2) < 3;
    const origAll = floorWalls().map(wall => ({
      id: wall.id,
      x1: wall.x1, y1: wall.y1, x2: wall.x2, y2: wall.y2,
    }));
    const movedOrig = origAll.find(ow => ow.id === w.id);
    const tol = 4;

    function applyWallPositions(dx, dy) {
      origAll.forEach(ow => {
        const wall = floorWalls().find(x => x.id === ow.id);
        if (!wall) return;
        if (wall.id === w.id) {
          if (isVert) {
            wall.x1 = ow.x1 + dx;
            wall.x2 = ow.x2 + dx;
          } else {
            wall.y1 = ow.y1 + dy;
            wall.y2 = ow.y2 + dy;
          }
          return;
        }
        if (isVert && movedOrig) {
          const oldX = movedOrig.x1;
          if (Math.abs(ow.x1 - oldX) <= tol) wall.x1 = ow.x1 + dx;
          if (Math.abs(ow.x2 - oldX) <= tol) wall.x2 = ow.x2 + dx;
        } else if (!isVert && movedOrig) {
          const oldY = movedOrig.y1;
          if (Math.abs(ow.y1 - oldY) <= tol) wall.y1 = ow.y1 + dy;
          if (Math.abs(ow.y2 - oldY) <= tol) wall.y2 = ow.y2 + dy;
        }
      });
    }

    function mv(e) {
      const cur = svgPoint(e);
      applyWallPositions(cur.x - start.x, cur.y - start.y);
      renderWalls();
      renderDoors();
    }
    async function up() {
      document.removeEventListener('mousemove', mv);
      document.removeEventListener('mouseup', up);
      try {
        const res = await api('/api/admin/wall/move', {
          method: 'POST',
          body: JSON.stringify({
            wall_id: w.id,
            x1: Math.round(w.x1), y1: Math.round(w.y1),
            x2: Math.round(w.x2), y2: Math.round(w.y2),
          }),
        });
        if (res.synced_places && res.synced_places.length) {
          toast('Стена сдвинута, локации обновлены: ' + res.synced_places.join(', '), 'success');
        }
        await loadAll(true);
      } catch (e) { toast(e.message || 'Ошибка', 'error'); }
    }
    document.addEventListener('mousemove', mv);
    document.addEventListener('mouseup', up);
  }

  function startDoorDrag(evt, d, w) {
    evt.preventDefault();
    const dx = w.x2 - w.x1, dy = w.y2 - w.y1, len2 = dx * dx + dy * dy;
    const dw = d.width || DOOR_W_1M;
    function mv(e) {
      const pt = svgPoint(e);
      const raw = ((pt.x - w.x1) * dx + (pt.y - w.y1) * dy) / len2;
      d.position = clampDoorPosition(w, raw, dw);
      renderDoors();
    }
    async function up() {
      document.removeEventListener('mousemove', mv);
      document.removeEventListener('mouseup', up);
      try {
        await api('/api/admin/door/move', {
          method: 'POST',
          body: JSON.stringify({ door_id: d.id, position: d.position }),
        });
      } catch (e) { toast(e.message || 'Ошибка', 'error'); }
    }
    document.addEventListener('mousemove', mv);
    document.addEventListener('mouseup', up);
  }

  async function deleteDoor() {
    if (!selection || selection.type !== 'door' || !selection.door) return;
    try {
      await api('/api/admin/door/' + selection.door.id, { method: 'DELETE' });
      clearSelection();
      await loadAll(true);
      toast('Дверь удалена', 'success');
    } catch (e) { toast('Ошибка', 'error'); }
  }

  async function loadFloors() {
    try {
      const data = await api('/api/floors');
      if (data.success && Array.isArray(data.floors) && data.floors.length) {
        availableFloors = data.floors;
        const nums = availableFloors.map(f => f.number);
        if (!nums.includes(currentFloor)) {
          currentFloor = availableFloors[0].number;
        }
      }
    } catch (e) {
      console.warn('Не удалось загрузить этажи', e);
    }
    renderFloorButtons();
  }

  function renderFloorButtons() {
    const bar = $('floor-toggle-bar');
    if (!bar) return;
    bar.innerHTML = availableFloors.map(f => {
      const label = f.label || f.name || `Этаж ${f.number}`;
      const active = Number(f.number) === Number(currentFloor);
      return `<button type="button" onclick="setFloor(${f.number})" id="floor-btn-${f.number}"${active ? ' style="background:#0ea5e9;"' : ''}>${label}</button>`;
    }).join('');
  }

  // --- Walls / doors ---
  window.setFloor = function (n) {
    currentFloor = n;
    selection = null;
    clearSelection();
    renderFloorButtons();
    loadAll(true);
  };

  function syncEditModes() {
    $('mode-label').style.display = (wallMode || wallMoveMode || doorMode) ? 'inline-flex' : 'none';
    $('door-width-bar').style.display = doorMode ? 'inline-flex' : 'none';
    $('btn-wall-mode')?.classList.toggle('active', wallMode);
    $('btn-wall-move')?.classList.toggle('active', wallMoveMode);
    $('btn-door-mode')?.classList.toggle('active', doorMode);
    updateEditLayerPointerEvents();
    if (!wallMode && !doorMode && !wallMoveMode) render();
  }

  window.toggleWallMode = function () {
    wallMode = !wallMode;
    if (wallMode) { doorMode = false; wallMoveMode = false; }
    wallStart = null;
    $('mode-label').textContent = wallMode ? 'Стены: 2 клика (можно по существующим)' : '';
    syncEditModes();
  };

  window.toggleWallMoveMode = function () {
    wallMoveMode = !wallMoveMode;
    if (wallMoveMode) { wallMode = false; doorMode = false; }
    wallStart = null;
    $('mode-label').textContent = wallMoveMode
      ? 'Тяните отдельный отрезок стены – каждая локация обновится сама'
      : '';
    syncEditModes();
  };

  window.toggleDoorMode = function () {
    doorMode = !doorMode;
    if (doorMode) { wallMode = false; wallMoveMode = false; }
    $('mode-label').textContent = doorMode ? 'Двери: клик по стене' : '';
    syncEditModes();
  };

  window.loadAll = loadAll;
  window.loadCategories = loadCategories;
  window.fixLocation = () => fixLocation(false);
  window.saveLocation = saveLocation;
  window.deleteLocation = deleteLocation;
  window.saveDesk = saveDesk;
  window.rotateDesk = rotateDesk;
  window.deleteDesk = deleteDesk;
  window.deleteDoor = deleteDoor;
  window.zoom = d => { zoomLevel = Math.max(0.3, Math.min(3, zoomLevel + d)); applyZoom(); };
  window.zoomReset = () => { zoomLevel = 1; applyZoom(); };

  window.addEventListener('error', event => {
    toast(friendlyError(event.error || event.message, 'Ошибка редактора. Обновите страницу и попробуйте ещё раз.'), 'error');
  });
  window.addEventListener('unhandledrejection', event => {
    toast(friendlyError(event.reason, 'Ошибка запроса. Попробуйте ещё раз.'), 'error');
  });

  function applyZoom() {
    const svg = $('canvas');
    svg.style.width = (SVG_W * zoomLevel) + 'px';
    svg.style.height = (SVG_H * zoomLevel) + 'px';
  }

  async function createWall(a, b) {
    const dx = Math.abs(b.x - a.x), dy = Math.abs(b.y - a.y);
    if (dx < 20 && dy < 20) return;
    await api('/api/admin/wall/create', {
      method: 'POST',
      body: JSON.stringify({
        x1: Math.round(a.x), y1: Math.round(a.y),
        x2: Math.round(dx >= dy ? b.x : a.x),
        y2: Math.round(dx >= dy ? a.y : b.y),
        floor: currentFloor,
      }),
    });
    await loadAll(true);
  }

  async function deleteWall(id) {
    await api('/api/admin/wall/' + id, { method: 'DELETE' });
    await loadAll(true);
  }

  async function addDoorAtWall(w, pt) {
    const dx = w.x2 - w.x1, dy = w.y2 - w.y1, len2 = dx * dx + dy * dy;
    if (len2 < 1) return;
    const width = parseInt($('door-width-select')?.value || DOOR_W_1M, 10);
    const raw = ((pt.x - w.x1) * dx + (pt.y - w.y1) * dy) / len2;
    const pos = clampDoorPosition(w, raw, width);
    await api('/api/admin/door/create', {
      method: 'POST',
      body: JSON.stringify({ wall_id: w.id, position: pos, floor: currentFloor, width }),
    });
    await loadAll(true);
  }

  $('canvas').addEventListener('mousedown', evt => {
    const pt = svgPoint(evt);
    if (wallMode) {
      handleWallModeClick(pt);
      return;
    }
    if (evt.target.getAttribute('fill') === '#f1f5f9') clearSelection();
  });

  $('prop-location-zone')?.addEventListener('change', () => {
    updateZoneFields();
    loadVariantsForSelection();
  });
  $('prop-category')?.addEventListener('change', () => {
    const z = selectedZone();
    if (!isRoomZone(z)) {
      loadVariantsForSelection();
      return;
    }
    const nameInput = $('prop-name');
    const selectedName = $('prop-category')?.selectedOptions?.[0]?.textContent
      ?.replace(/\s+—\s+не помещается$/, '')
      ?.trim();
    if (nameInput && selectedName) nameInput.value = selectedName;
  });
  $('door-width-edit')?.addEventListener('change', async () => {
    if (!selection || selection.type !== 'door') return;
    const d = selection.door;
    const width = parseInt($('door-width-edit').value, 10);
    try {
      await api('/api/admin/door/move', {
        method: 'POST',
        body: JSON.stringify({ door_id: d.id, width }),
      });
      d.width = width;
      renderDoors();
      toast('Ширина двери обновлена', 'success');
    } catch (e) { toast(e.message || 'Ошибка', 'error'); }
  });

  document.addEventListener('DOMContentLoaded', async () => {
    await loadLocationZones();
    await loadCategories();
    await loadFloors();
    await loadAll();
  });
})();
