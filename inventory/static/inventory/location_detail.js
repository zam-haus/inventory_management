(() => {
    if (typeof bootstrap === 'undefined' || !bootstrap.Tooltip) return;

    const tooltips = [];
    document.querySelectorAll('.location-header [data-bs-toggle="tooltip"], .location-detail [data-bs-toggle="tooltip"], .item-header [data-bs-toggle="tooltip"], .item-detail [data-bs-toggle="tooltip"]').forEach(element => {
        const tooltip = new bootstrap.Tooltip(element, {container: 'body', trigger: 'hover focus'});
        tooltips.push(tooltip);
        // Tapping a help control also reveals its explanation on touch screens.
        if (element.classList.contains('location-help') || element.classList.contains('item-help')) {
            element.addEventListener('click', () => {
                element.focus();
                tooltip.show();
            });
        }
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') tooltips.forEach(tooltip => tooltip.hide());
    });
})();

(() => {
    const detail = document.querySelector('.location-detail[data-lightbox-gallery-label]');
    if (!detail || !window.setupPhotoLightbox) return;
    const data = detail.dataset;
    const labels = {
        gallery: data.lightboxGalleryLabel, close: data.lightboxCloseLabel,
        previous: data.lightboxPreviousLabel, next: data.lightboxNextLabel,
        error: data.lightboxErrorMessage, retry: data.lightboxRetryLabel,
        loading: data.lightboxLoadingLabel,
    };
    // The overview photo opens alone; arrows browse the photos of one item.
    const groups = [
        [...detail.querySelectorAll('a.location-overview-photo')],
        ...[...detail.querySelectorAll('.location-photos')].map(photos => [...photos.querySelectorAll('a.location-photo')]),
    ];
    groups.forEach(links => window.setupPhotoLightbox(links, {className: 'location-lightbox', labels}));
})();
