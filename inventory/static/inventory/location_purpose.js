// The purpose editor on the location page: a dialog opened by ✏️ next to the name. It submits
// normally; on errors the page comes back with the dialog open (data-open).
(() => {
    const editor = document.getElementById('location-purpose-editor');
    if (!editor || typeof bootstrap === 'undefined' || !bootstrap.Modal) return;
    const input = editor.querySelector('input[name="purpose"]');
    const counter = editor.querySelector('[data-purpose-count]');
    const updateCounter = () => { counter.textContent = `${Array.from(input.value).length} / 50`; };

    editor.classList.add('modal', 'fade');
    editor.querySelectorAll('[data-purpose-enhanced]').forEach(element => { element.hidden = false; });
    const modal = new bootstrap.Modal(editor);
    document.querySelectorAll('[data-purpose-open]').forEach(trigger => {
        trigger.addEventListener('click', event => {
            event.preventDefault();
            modal.show(trigger);
        });
    });
    input.addEventListener('input', updateCounter);
    editor.addEventListener('shown.bs.modal', () => { input.focus(); input.select(); });
    editor.addEventListener('hidden.bs.modal', () => {
        if (editor.dataset.open === 'true') return;  // keep what was entered after a failed save
        editor.querySelector('form').reset();
        updateCounter();
    });
    if (editor.dataset.open === 'true' || window.location.hash === '#location-purpose-editor') modal.show();
})();
