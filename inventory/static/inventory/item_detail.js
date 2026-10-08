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
    const links = Array.from(gallery.querySelectorAll('.item-image-link'));
    window.setupPhotoLightbox?.(links, {
        className: 'item-lightbox',
        labels: {
            gallery: gallery.dataset.galleryLabel, close: gallery.dataset.closeLabel,
            previous: gallery.dataset.previousLabel, next: gallery.dataset.nextLabel,
            error: gallery.dataset.errorMessage, retry: gallery.dataset.retryLabel,
            loading: gallery.dataset.loadingLabel,
        },
        onShow: (viewer, source) => {
            const ocr = source.closest('.item-image-frame').querySelector('.item-image-ocr');
            if (ocr) {
                const enlargedOcr = ocr.cloneNode(true);
                enlargedOcr.open = false;
                setupOcr(enlargedOcr);
                viewer.figure.appendChild(enlargedOcr);
            }
        },
    });
})();
