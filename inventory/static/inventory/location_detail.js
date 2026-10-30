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
    const setup = links => window.setupPhotoLightbox(links, {className: 'location-lightbox', labels});
    // The overview photo and each quick-item photo open alone. Those of the items and unique items open below their
    // rows (results.js).
    const groups = [
        [...detail.querySelectorAll('a.location-overview-photo')],
        ...[...detail.querySelectorAll('.location-quick-readonly a.location-quick-photo')].map(link => [link]),
    ];
    groups.forEach(setup);
    // Editable quick-items (location_quick_items.js) set up their single photo, also once it is uploaded.
    window.setupLocationPhotoLink = link => setup([link]);
})();
