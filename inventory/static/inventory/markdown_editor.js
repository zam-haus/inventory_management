// Markdown fields (widgets.MarkdownEditor) get a WYSIWYG editor (TOAST UI Editor) that writes the Markdown
// back into their textarea, which is what the form sends; without the editor, the textarea stays. Images
// pasted, dropped or chosen in the editor are uploaded to the URL in data-markdown-editor and embedded with
// the URL the server answers. The image button opens the device's file choice (on phones: camera or gallery)
// instead of the editor's own image popup, which does not fit narrow screens. Without an upload URL (empty
// data-markdown-editor) there is no image button, and pasted or dropped images are left out. Resetting the form
// (e.g. closing its modal) resets the editor as well.
(() => {
    if (!window.toastui?.Editor) return;
    const language = (document.documentElement.lang || '').toLowerCase().startsWith('de') ? 'de-DE' : 'en-US';
    // Only what the rendering keeps (templatetags/mytemplatetags.py, MARKDOWN_TAGS); one group, so that all
    // buttons fit beside each other on a phone.
    const toolbarItems = image => [['heading', 'bold', 'italic', 'ul', 'ol', 'link', ...(image ? [image] : [])]];

    function csrfToken(form) {
        return form?.querySelector('[name=csrfmiddlewaretoken]')?.value
            || document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)?.[1] || '';
    }

    async function upload(textarea, blob) {
        const body = new FormData();
        body.append('image', blob, blob.name || 'image.png');
        const response = await fetch(textarea.dataset.markdownEditor, {
            method: 'POST', body, credentials: 'same-origin',
            headers: {'X-CSRFToken': csrfToken(textarea.form), 'Accept': 'application/json'},
        });
        const answer = await response.json().catch(() => ({}));
        if (!response.ok || !answer.url) throw new Error(answer.error || textarea.dataset.uploadError);
        return answer.url;
    }

    function setup(textarea) {
        const holder = document.createElement('div');
        holder.className = 'markdown-editor';
        holder.dataset.observerPrivate = '';  // not for observers of the whole page (observer_guard.js)
        const message = document.createElement('div');
        message.className = 'markdown-editor-message';
        message.setAttribute('role', 'status');
        message.hidden = true;
        const show = (text, error = false) => {
            message.textContent = text;
            message.classList.toggle('markdown-editor-error', error);
            message.hidden = !text;
        };
        // Uploads an image and calls insert(url) with its URL; tells while it uploads and why it failed.
        const uploadImage = (blob, insert) => {
            show(textarea.dataset.uploading);
            upload(textarea, blob).then(url => {
                show('');
                insert(url);
            }).catch(error => show(error.message || textarea.dataset.uploadError, true));
        };
        const imageButton = document.createElement('button');
        imageButton.type = 'button';
        imageButton.className = 'toastui-editor-toolbar-icons image';
        imageButton.setAttribute('aria-label', textarea.dataset.imageLabel);
        const imageInput = document.createElement('input');
        imageInput.type = 'file';
        imageInput.accept = 'image/*';
        imageInput.hidden = true;
        textarea.after(holder, message, imageInput);
        textarea.hidden = true;
        // Only what people change is written back: the editor may write unchanged Markdown differently.
        let changed = false;
        const editor = new window.toastui.Editor({
            el: holder, initialValue: textarea.value, initialEditType: 'wysiwyg', previewStyle: 'tab',
            height: 'auto', minHeight: '120px', language, usageStatistics: false, autofocus: false,
            toolbarItems: toolbarItems(textarea.dataset.markdownEditor &&
                {name: 'image-upload', el: imageButton, tooltip: textarea.dataset.imageLabel}),
            events: {
                change: () => {
                    if (!changed && editor.getMarkdown() === textarea.value) return;
                    changed = true;
                    textarea.value = editor.getMarkdown();
                },
            },
            hooks: {
                // Pasted or dropped images (without an upload URL: left out, not embedded as data).
                addImageBlobHook: (blob, insert) => {
                    if (textarea.dataset.markdownEditor) uploadImage(blob, url => insert(url, ''));
                },
            },
        });
        imageButton.addEventListener('click', () => imageInput.click());
        imageInput.addEventListener('change', () => {
            [...imageInput.files].forEach(file => uploadImage(file, url => editor.exec('addImage', {imageUrl: url, altText: ''})));
            imageInput.value = '';
        });
        // The field's label focuses the editor.
        textarea.labels?.forEach(label => label.addEventListener('click', event => {
            event.preventDefault();
            editor.focus();
        }));
        // Read the reset value after the reset (the "reset" event comes before it).
        textarea.form?.addEventListener('reset', () => queueMicrotask(() => {
            editor.setMarkdown(textarea.value, false);
            changed = false;
            show('');
        }));
    }

    document.querySelectorAll('textarea[data-markdown-editor]').forEach(setup);
})();
