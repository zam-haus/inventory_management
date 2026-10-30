// Collapsed lists stay searchable: entries beyond the first five get hidden="until-found",
// so the browser's find-in-page (and links to a text fragment) also find them. Revealing a
// match fires beforematch, which expands the whole list; so does list-collapse:expand on an
// entry (results.js, when the arrow keys move onto it). Browsers without until-found hide them
// plainly. The entries are counted once, so that rows added later (the photos below a result,
// results.js) do not shift them. Without JavaScript, list_collapse.css hides them.
(() => {
    const value = 'onbeforematch' in document.body ? 'until-found' : '';
    document.querySelectorAll('.list-collapse-state').forEach(state => {
        const section = state.parentElement;
        const hidden = [...section.querySelectorAll('.list-collapse-list > li')].slice(5);
        const sync = () => hidden.forEach(item => {
            if (state.checked) item.removeAttribute('hidden');
            else item.setAttribute('hidden', value);
        });
        const expand = () => {
            state.checked = true;
            sync();
        };
        hidden.forEach(item => item.addEventListener('beforematch', expand));
        section.addEventListener('list-collapse:expand', expand);
        state.addEventListener('change', sync);
        section.classList.add('list-collapse-searchable');
        sync();
    });
})();
