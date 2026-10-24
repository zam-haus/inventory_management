// A label image's admin page: drag over the original to choose the part to keep; the margins to cut off
// (crop_left … crop_bottom, in pixels of the original) follow, and the part kept is shown.
document.addEventListener('DOMContentLoaded', () => {
    const area = document.querySelector('[data-crop]');
    if (!area) return;
    const image = area.querySelector('img');
    const box = area.querySelector('[data-crop-box]');
    const input = side => document.getElementById(`id_crop_${side}`);
    const width = Number(area.dataset.width);
    const height = Number(area.dataset.height);
    Object.assign(area.style, {position: 'relative', display: 'inline-block', cursor: 'crosshair', userSelect: 'none'});
    Object.assign(box.style, {position: 'absolute', outline: '2px dashed #c00', boxShadow: '0 0 0 9999px rgba(255,255,255,.6)',
                              pointerEvents: 'none'});
    area.style.overflow = 'hidden';
    image.draggable = false;
    image.style.display = 'block';

    const scale = () => image.clientWidth / width;
    function show() {
        const s = scale();
        const [left, top, right, bottom] = ['left', 'top', 'right', 'bottom'].map(side => Number(input(side).value) || 0);
        Object.assign(box.style, {left: `${left * s}px`, top: `${top * s}px`,
                                  width: `${Math.max(0, width - left - right) * s}px`,
                                  height: `${Math.max(0, height - top - bottom) * s}px`});
    }
    function point(event) {
        const rect = image.getBoundingClientRect();
        const s = scale();
        return [Math.min(width, Math.max(0, Math.round((event.clientX - rect.left) / s))),
                Math.min(height, Math.max(0, Math.round((event.clientY - rect.top) / s)))];
    }
    let start = null;
    area.addEventListener('pointerdown', event => {
        start = point(event);
        area.setPointerCapture(event.pointerId);
    });
    area.addEventListener('pointermove', event => {
        if (!start) return;
        const end = point(event);
        const [left, right] = [Math.min(start[0], end[0]), Math.max(start[0], end[0])];
        const [top, bottom] = [Math.min(start[1], end[1]), Math.max(start[1], end[1])];
        if (right - left < 1 || bottom - top < 1) return;
        input('left').value = left;
        input('top').value = top;
        input('right').value = width - right;
        input('bottom').value = height - bottom;
        show();
    });
    area.addEventListener('pointerup', () => { start = null; });
    ['left', 'top', 'right', 'bottom'].forEach(side => input(side)?.addEventListener('input', show));
    if (image.complete) show(); else image.addEventListener('load', show);
});
