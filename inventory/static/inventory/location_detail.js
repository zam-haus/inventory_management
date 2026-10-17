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
    // The overview photo opens alone; arrows browse the photos of one item.
    const groups = [
        [...detail.querySelectorAll('a.location-overview-photo')],
        ...[...detail.querySelectorAll('.location-photos')].map(photos => [...photos.querySelectorAll('a.location-photo')]),
        ...[...detail.querySelectorAll('.location-quick-readonly a.location-quick-photo')].map(link => [link]),
    ];
    groups.forEach(setup);
    // Editable quick-items (location_quick_items.js) set up their single photo, also once it is uploaded.
    window.setupLocationPhotoLink = link => setup([link]);
})();
