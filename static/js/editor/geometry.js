/**
 * Геометрия редактора планировки (чистые функции без состояния).
 */
'use strict';

function effectiveRectForRotation(x, y, w, h, rotation = 0) {
    const rot = (parseInt(rotation, 10) || 0) % 360;
    const fw = +w;
    const fh = +h;
    const cx = +x + fw / 2;
    const cy = +y + fh / 2;
    const effW = rot % 180 === 90 ? fh : fw;
    const effH = rot % 180 === 90 ? fw : fh;
    return { x: cx - effW / 2, y: cy - effH / 2, w: effW, h: effH };
}

function applyEffectiveRectDelta(x, y, effX, effY, w, h, rotation = 0) {
    const orig = effectiveRectForRotation(x, y, w, h, rotation);
    return { x: +x + (effX - orig.x), y: +y + (effY - orig.y) };
}

function rectsOverlap(ax, ay, aw, ah, bx, by, bw, bh, gap = 2) {
    return ax < bx + bw - gap && ax + aw > bx + gap && ay < by + bh - gap && ay + ah > by + gap;
}

function rectsMeaningfulOverlap(ax, ay, aw, ah, bx, by, bw, bh, minDepth = 4, edgeTouchMax = 16) {
    const ix = Math.max(ax, bx);
    const iy = Math.max(ay, by);
    const iw = Math.min(ax + aw, bx + bw) - ix;
    const ih = Math.min(ay + ah, by + bh) - iy;
    if (iw <= 0 || ih <= 0) return false;
    if (Math.min(iw, ih) <= edgeTouchMax) return false;
    return iw >= minDepth && ih >= minDepth;
}

function rectContains(ox, oy, ow, oh, ix, iy, iw, ih, pad = 0) {
    return ix >= ox + pad && iy >= oy + pad
        && ix + iw <= ox + ow - pad && iy + ih <= oy + oh - pad;
}

function deskCenterInParent(parent, x, y, w, h, rotation = 0) {
    const eff = effectiveRectForRotation(x, y, w, h, rotation);
    return deskEffectiveRectInParent(parent, eff.x, eff.y, eff.w, eff.h);
}

function deskEffectiveRectInParent(parent, ex, ey, ew, eh, inset = 0) {
    if (!parent || parent.width == null || parent.height == null) return false;
    return ex >= parent.x + inset
        && ey >= parent.y + inset
        && ex + ew <= parent.x + parent.width - inset
        && ey + eh <= parent.y + parent.height - inset;
}

function clampRectInParent(effX, effY, effW, effH, parent, inset = 0) {
    if (!parent || parent.width == null || parent.height == null) return null;
    const minX = parent.x + inset;
    const minY = parent.y + inset;
    const maxX = parent.x + parent.width - inset - effW;
    const maxY = parent.y + parent.height - inset - effH;
    if (maxX < minX || maxY < minY) return null;
    return {
        x: Math.max(minX, Math.min(effX, maxX)),
        y: Math.max(minY, Math.min(effY, maxY)),
    };
}

function clampRectInParentRotated(x, y, w, h, rotation, parent, inset = 0) {
    const eff = effectiveRectForRotation(x, y, w, h, rotation);
    const clamped = clampRectInParent(eff.x, eff.y, eff.w, eff.h, parent, inset);
    if (!clamped) return null;
    return applyEffectiveRectDelta(x, y, clamped.x, clamped.y, w, h, rotation);
}

function clampRectToFloorRotated(x, y, w, h, rotation, canvasW, canvasH, inset = 8) {
    const eff = effectiveRectForRotation(x, y, w, h, rotation);
    const maxX = canvasW - inset - eff.w;
    const maxY = canvasH - inset - eff.h;
    if (maxX < inset || maxY < inset) return null;
    const effX = Math.max(inset, Math.min(eff.x, maxX));
    const effY = Math.max(inset, Math.min(eff.y, maxY));
    return applyEffectiveRectDelta(x, y, effX, effY, w, h, rotation);
}
