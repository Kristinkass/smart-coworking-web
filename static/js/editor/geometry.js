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

function rectsMeaningfulOverlap(ax, ay, aw, ah, bx, by, bw, bh, minDepth = 4) {
    const ix = Math.max(ax, bx);
    const iy = Math.max(ay, by);
    const iw = Math.min(ax + aw, bx + bw) - ix;
    const ih = Math.min(ay + ah, by + bh) - iy;
    if (iw <= 0 || ih <= 0) return false;
    return iw >= minDepth && ih >= minDepth;
}

function rectContains(ox, oy, ow, oh, ix, iy, iw, ih, pad = 0) {
    return ix >= ox + pad && iy >= oy + pad
        && ix + iw <= ox + ow - pad && iy + ih <= oy + oh - pad;
}

function deskCenterInParent(parent, x, y, w, h) {
    const cx = x + w / 2;
    const cy = y + h / 2;
    return cx >= parent.x && cx <= parent.x + parent.width
        && cy >= parent.y && cy <= parent.y + parent.height;
}
