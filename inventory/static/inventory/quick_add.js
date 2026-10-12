// Quick add of a photo or file on item and unique item pages. Without
// JavaScript the "+" buttons lead to the edit form instead.
(() => {
    if (typeof bootstrap === 'undefined') return;
    document.querySelectorAll('[data-quick-open]').forEach(button => {
        const modalElement = document.getElementById(button.dataset.quickOpen);
        if (!modalElement) return;
        button.addEventListener('click', event => {
            event.preventDefault();
            bootstrap.Modal.getOrCreateInstance(modalElement).show(button);
        });
    });
    document.querySelectorAll('form[data-quick-form]').forEach(form => {
        const modalElement = form.closest('.modal');
        const tools = form.querySelector('[data-photo-tools]');
        const input = form.querySelector('input[type=file]');
        const editor = tools && window.PhotoEditor ? new PhotoEditor(tools) : null;
        const submit = form.querySelector('[type=submit]');
        modalElement.addEventListener('show.bs.modal', () => {
            if (!editor) return;
            tools.hidden = false;
            editor.attach(input, '');
        });
        modalElement.addEventListener('shown.bs.modal', () => input.focus());
        modalElement.addEventListener('hidden.bs.modal', () => {
            if (editor) editor.detach();
            form.reset();
            submit.disabled = false;
        });
        form.addEventListener('submit', async event => {
            submit.disabled = true;
            if (!editor) return;
            // A cropped, rotated or converted photo replaces the chosen one before sending.
            event.preventDefault();
            try {
                const file = await editor.result();
                if (file) PhotoEditor.setFile(input, file);
                form.submit();
            } catch {
                editor.say('photoError', true);
                submit.disabled = false;
            }
        });
    });
})();
