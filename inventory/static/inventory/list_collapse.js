// Collapsed lists stay searchable: entries beyond the first five get hidden="until-found",
// so the browser's find-in-page (and links to a text fragment) also find them. Revealing a
// match fires beforematch, which expands the whole list. Without support for it, or without
// JavaScript, list_collapse.css hides those entries as before.
(() => {
    if (!('onbeforematch' in document.body)) return;
    document.querySelectorAll('.list-collapse-state').forEach(state => {
        const section = state.parentElement;
        const hidden = [...section.querySelectorAll('.list-collapse-list > li')].slice(5);
        const sync = () => hidden.forEach(item => {
            if (state.checked) item.removeAttribute('hidden');
            else item.setAttribute('hidden', 'until-found');
        });
        hidden.forEach(item => item.addEventListener('beforematch', () => {
            state.checked = true;
            sync();
        }));
        state.addEventListener('change', sync);
        section.classList.add('list-collapse-searchable');
        sync();
    });
})();
