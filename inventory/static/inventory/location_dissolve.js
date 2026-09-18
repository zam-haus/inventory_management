(() => {
    const form = document.getElementById('dissolve-plan');
    if (!form) return;
    const rows = Array.from(form.querySelectorAll('[data-dissolve-row]'));
    const controls = row => ({
        deletion: row.querySelector('[data-delete] input[type="checkbox"]'),
        destination: row.querySelector('[data-destination] select'),
    });
    const sync = row => {
        const {deletion, destination} = controls(row);
        destination.disabled = deletion.checked || destination.dataset.moveForbidden === "true";
    };
    rows.forEach(row => {
        controls(row).deletion.addEventListener('change', () => sync(row));
        sync(row);
    });
    document.getElementById('dissolve-delete-all')?.addEventListener('click', () => {
        rows.forEach(row => {
            if (controls(row).deletion.disabled) return;
            controls(row).deletion.checked = true;
            sync(row);
        });
    });
    document.getElementById('dissolve-fill')?.addEventListener('click', () => {
        const bulk = document.getElementById('id_bulk_destination');
        const selected = bulk.options[bulk.selectedIndex];
        if (!selected || !selected.value) {
            if (window.jQuery?.fn.select2) window.jQuery(bulk).select2('open');
            else bulk.focus();
            return;
        }
        rows.forEach(row => {
            const {deletion, destination} = controls(row);
            if (destination.dataset.moveForbidden === "true") return;
            deletion.checked = false;
            sync(row);
            let option = Array.from(destination.options).find(option => option.value === selected.value);
            if (!option) {
                option = new Option(selected.text, selected.value);
                destination.add(option);
            }
            destination.value = selected.value;
            if (window.jQuery) window.jQuery(destination).trigger('change');
            else destination.dispatchEvent(new Event('change', {bubbles: true}));
        });
    });
})();
