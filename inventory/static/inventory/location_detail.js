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
