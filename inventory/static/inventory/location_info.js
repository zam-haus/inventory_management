// A location's code chip ([data-location-info], location_display.code_html) shows the location in brief in a
// window (location_info_modal.html): its path, title, overview photo and description, with a button to its
// page. The chip works by click, Enter or space, also inside a link, whose name leads to the page as before.
// Closing the window returns the focus to the chip. Once a location is in the window, it sends
// "location-info:shown" (for optional apps, e.g. the small map of the maps app).
(() => {
    const modal = document.getElementById('location-info');
    const content = modal?.querySelector('[data-location-info-content]');
    if (!content || !window.bootstrap || !window.fetch) return;
    let controller = null;
    let opener = null;

    async function show(pk) {
        controller?.abort();
        controller = new AbortController();
        try {
            const response = await fetch(`/loc/${pk}/info/`, {signal: controller.signal, credentials: 'same-origin'});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            content.innerHTML = await response.text();
        } catch (failure) {
            if (failure.name === 'AbortError') return;
            content.innerHTML = '';
            const message = document.createElement('p');
            message.className = 'modal-body text-danger';
            message.textContent = content.dataset.error;
            content.append(message);
        }
        window.bootstrap.Modal.getOrCreateInstance(modal).show();
        const announce = () => content.dispatchEvent(new CustomEvent('location-info:shown', {bubbles: true}));
        if (modal.classList.contains('show')) announce();
        else modal.addEventListener('shown.bs.modal', announce, {once: true});
    }

    function open(event, chip) {
        event.preventDefault();
        event.stopPropagation();
        // A chip in the window (the path) keeps the first opener, which gets the focus back.
        if (!modal.contains(chip)) opener = chip;
        show(chip.dataset.locationInfo);
    }

    document.addEventListener('click', event => {
        const chip = event.target.closest('[data-location-info]');
        if (chip && event.button === 0) open(event, chip);
    }, true);
    document.addEventListener('keydown', event => {
        const chip = event.target.closest?.('[data-location-info]');
        if (chip && (event.key === 'Enter' || event.key === ' ')) open(event, chip);
    }, true);
    modal.addEventListener('hidden.bs.modal', () => {
        if (opener?.isConnected) opener.focus();
        opener = null;
    });
})();
