// The editors for one field of a location on its page (purpose, physical description): each
// [data-field-editor] section becomes a dialog, opened by [data-field-editor-open="<its id>"]. It submits
// normally; on errors the page comes back with that dialog open (data-open).
(() => {
    if (typeof bootstrap === 'undefined' || !bootstrap.Modal) return;
    document.querySelectorAll('[data-field-editor]').forEach(editor => {
        const input = editor.querySelector('input:not([type="hidden"]), textarea');
        const counter = editor.querySelector('[data-field-editor-count]');
        const updateCounter = () => {
            if (counter) counter.textContent = `${Array.from(input.value).length} / ${input.maxLength}`;
        };

        editor.classList.add('modal', 'fade');
        editor.querySelectorAll('[data-field-editor-enhanced]').forEach(element => { element.hidden = false; });
        const modal = new bootstrap.Modal(editor);
        document.querySelectorAll(`[data-field-editor-open="${editor.id}"]`).forEach(trigger => {
            trigger.addEventListener('click', event => {
                event.preventDefault();
                modal.show(trigger);
            });
        });
        input.addEventListener('input', updateCounter);
        editor.addEventListener('hidden.bs.modal', () => {
            if (editor.dataset.open === 'true') return;  // keep what was entered after a failed save
            editor.querySelector('form').reset();
            updateCounter();
        });
        if (editor.dataset.open === 'true' || window.location.hash === `#${editor.id}`) modal.show();
    });
})();
