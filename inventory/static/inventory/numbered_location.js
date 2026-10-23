// Adding a numbered location (numbered_location_create.html): only the fields of the chosen way to
// get a number are shown. Hidden fields are disabled, so they are not sent; the server ignores them too.
(() => {
    const form = document.querySelector('[data-numbering-form]');
    if (!form) return;
    const fieldsFor = {reserved: ['reserved'], wish: ['wish', 'expected'], auto: ['expected']};
    const update = () => {
        const mode = form.querySelector('input[name="mode"]:checked')?.value;
        for (const name of ['reserved', 'wish', 'expected']) {
            const input = form.elements[name];
            const group = input?.closest('.mb-3');
            if (!group) continue;
            const shown = (fieldsFor[mode] || []).includes(name);
            group.hidden = !shown;
            input.disabled = !shown;
        }
    };
    form.querySelectorAll('input[name="mode"]').forEach(choice => choice.addEventListener('change', update));
    update();
})();
