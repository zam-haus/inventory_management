(() => {
    const gallery = document.querySelector('.item-gallery');
    if (!gallery) return;

    const setupOcr = details => {
        let dismissedWithEscape = false;
        // Reading, selecting and scrolling OCR text must not swipe or close the photo.
        ['click', 'dblclick', 'pointerdown', 'pointermove', 'pointerup', 'mousedown',
            'mousemove', 'mouseup', 'touchstart', 'touchmove', 'touchend', 'touchcancel',
            'wheel'].forEach(type => {
            details.addEventListener(type, event => { event.stopPropagation(); });
        });
        details.addEventListener('keydown', event => {
            if (event.key === 'Escape' && details.open) {
                event.preventDefault();
                event.stopPropagation();
                details.open = false;
                dismissedWithEscape = true;
                details.querySelector('summary').focus();
            }
        });
        details.addEventListener('keyup', event => {
            if (details.open || (event.key === 'Escape' && dismissedWithEscape)) {
                event.stopPropagation();
            }
            dismissedWithEscape = false;
        });
    };
    gallery.querySelectorAll('.item-image-ocr').forEach(setupOcr);
    if (typeof SimpleLightbox === 'undefined') return;
    const links = Array.from(gallery.querySelectorAll('.item-image-link'));
    if (!links.length) return;

    const lightbox = new SimpleLightbox(links, {
        className: 'item-lightbox',
        // Descriptions remain below thumbnails; do not interpret them as HTML.
        captions: false,
        fileExt: false,
        history: false,
        enableKeyboard: true,
        loop: true,
        swipeClose: false,
        scrollZoom: false,
        maxZoom: 1,
        doubleTapZoom: 1,
        alertErrorMessage: gallery.dataset.errorMessage,
    });

    const wrapper = lightbox.domNodes.wrapper;
    wrapper.setAttribute('aria-label', gallery.dataset.galleryLabel);
    wrapper.setAttribute('aria-modal', 'true');
    lightbox.domNodes.closeButton.setAttribute('aria-label', gallery.dataset.closeLabel);
    wrapper.querySelector('.sl-prev').setAttribute('aria-label', gallery.dataset.previousLabel);
    wrapper.querySelector('.sl-next').setAttribute('aria-label', gallery.dataset.nextLabel);

    let opener = null;
    lightbox.on('show.simplelightbox', event => { opener = event.currentTarget; });
    lightbox.on('closed.simplelightbox', () => { if (opener) opener.focus(); });
    lightbox.on(['shown.simplelightbox', 'changed.simplelightbox'], () => {
        if (lightbox.currentImage) {
            const source = lightbox.relatedElements[lightbox.currentImageIndex];
            lightbox.currentImage.alt = source.querySelector('img').alt;
            lightbox.domNodes.image.querySelector('.item-image-ocr')?.remove();
            const ocr = source.closest('.item-image-frame').querySelector('.item-image-ocr');
            if (ocr) {
                const enlargedOcr = ocr.cloneNode(true);
                enlargedOcr.open = false;
                setupOcr(enlargedOcr);
                lightbox.domNodes.image.appendChild(enlargedOcr);
            }
        }
    });

    // Ignore clicks generated after dragging, swiping or multi-touch gestures.
    let start = null;
    let moved = false;
    const pointers = new Set();
    wrapper.addEventListener('pointerdown', event => {
        if (!pointers.size) {
            start = {x: event.clientX, y: event.clientY};
            moved = false;
        } else {
            moved = true;
        }
        pointers.add(event.pointerId);
    });
    wrapper.addEventListener('pointermove', event => {
        if (start && pointers.has(event.pointerId) &&
            Math.hypot(event.clientX - start.x, event.clientY - start.y) > 8) {
            moved = true;
        }
    });
    window.addEventListener('pointerup', event => { pointers.delete(event.pointerId); });
    window.addEventListener('pointercancel', event => {
        if (pointers.delete(event.pointerId)) moved = true;
    });
    wrapper.addEventListener('click', event => {
        if (!moved && event.target === lightbox.currentImage) lightbox.close();
    });
})();
