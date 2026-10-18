// Move a unique item in a dialog: choose the new location in the search, or scan its label
// with the field's QR button (location_scan.js). Without JavaScript, "Move" opens the edit form.
(() => {
    const modalElement = document.getElementById('move-modal');
    if (!modalElement || typeof bootstrap === 'undefined') return;
    // The scanner opens its own dialog above this one, which needs the focus.
    const modal = new bootstrap.Modal(modalElement, {focus: false});
    document.querySelectorAll('[data-move-open]').forEach(button => button.addEventListener('click', event => {
        event.preventDefault();
        modal.show(button);
    }));
})();
