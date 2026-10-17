(() => {
    const section = document.querySelector('[data-quick-items]');
    const list = section && section.querySelector('[data-quick-items-list]');
    if (!list || !window.fetch || !('content' in document.createElement('template'))) return;

    const UNDO_DELAY = 5000;
    const createForm = list.querySelector('[data-quick-items-create]');
    const newRow = createForm.closest('li');
    const newInput = createForm.elements.name;
    const template = section.querySelector('[data-quick-item-template]');
    const status = section.querySelector('[data-quick-items-status]');
    const csrfToken = createForm.elements.csrfmiddlewaretoken.value;
    const data = section.dataset;
    const texts = {
        networkError: data.textNetworkError, saveError: data.textSaveError,
        added: data.textAdded, deleted: data.textDeleted,
        deleteScheduled: data.textDeleteScheduled, deleteUndone: data.textDeleteUndone,
        details: data.textDetails, delete: data.textDelete,
        photo: data.textPhoto, photoOf: data.textPhotoOf, photoAdded: data.textPhotoAdded,
        replacePhoto: data.textReplacePhoto, actions: data.textActions,
    };
    const pendingDeletes = new Set();
    section.style.setProperty('--quick-undo-delay', `${UNDO_DELAY / 1000}s`);

    const normalize = value => value.split(/\s+/).filter(Boolean).join(' ');
    const format = (text, name) => text.replace('{name}', () => name);

    function announce(message) {
        // Clearing first makes screen readers repeat identical messages.
        status.textContent = '';
        window.setTimeout(() => { status.textContent = message; }, 50);
    }

    function updateCount() {
        // Quick-items count as items: in the panel heading and the overview at the top of the page.
        const quick = list.querySelectorAll('[data-quick-item]').length;
        const count = Number(data.detailedCount || 0) + quick;
        document.querySelectorAll('[data-items-count]').forEach(element => { element.textContent = count; });
        document.querySelectorAll('[data-items-empty]').forEach(element => { element.hidden = count > 0; });
    }

    async function post(url, data = {}) {
        const body = new FormData();
        body.set('csrfmiddlewaretoken', csrfToken);
        Object.entries(data).forEach(([key, value]) => body.set(key, value));
        let response;
        try {
            response = await fetch(url, {
                method: 'POST', body, headers: {Accept: 'application/json'}, credentials: 'same-origin',
            });
        } catch {
            throw Object.assign(new Error(texts.networkError), {status: 0});
        }
        let result = null;
        try { result = await response.json(); } catch { /* error pages are HTML */ }
        if (!response.ok || !result || !result.ok) {
            throw Object.assign(new Error((result && result.error) || texts.saveError), {status: response.status});
        }
        return result;
    }

    // Operations on one row run in order, so edits made while the row is still
    // being created wait for its URLs. A failed creation skips the rest.
    function enqueue(row, task) {
        row.queue = row.queue.then(() => (row.failed ? undefined : task()));
    }

    function focusAfter(element) {
        const next = element.nextElementSibling;
        (next ? next.querySelector('input[name="name"]') : newInput).focus();
    }

    function setLabels(row, name) {
        row.menu.setAttribute('aria-label', format(texts.actions, name));
        row.details.setAttribute('aria-label', format(texts.details, name));
        row.deleteButton.setAttribute('aria-label', format(texts.delete, name));
        if (row.photoInput) row.photoInput.setAttribute('aria-label', format(texts.photo, name));
        if (row.photoLink.getAttribute('href')) row.photoImage.alt = format(texts.photoOf, name);
    }

    function showPhoto(row, photo) {
        if (!photo) return;
        row.photoLink.href = photo.url;
        row.photoImage.src = photo.thumbnail;
        row.photoLink.hidden = false;
        if (row.photoButton) {
            row.photoButton.title = texts.replacePhoto;
            row.photoButton.querySelector('[data-quick-photo-label]').textContent = texts.replacePhoto;
        }
        setLabels(row, row.saved);
    }

    function uploadPhoto(row) {
        const file = row.photoInput.files[0];
        if (!file) return;
        row.li.classList.add('is-uploading');
        enqueue(row, async () => {
            try {
                const result = await post(row.photoUrl, {image: file});
                showPhoto(row, result.entry.photo);
                announce(format(texts.photoAdded, row.saved));
            } catch (error) {
                announce(error.message);
            } finally {
                row.li.classList.remove('is-uploading');
                row.photoInput.value = '';
            }
        });
    }

    function applyEntry(row, entry) {
        row.updateUrl = entry.update_url;
        row.deleteUrl = entry.delete_url;
        row.saved = entry.name;
        row.nameForm.action = entry.update_url;
        row.deleteForm.action = entry.delete_url;
        row.details.href = entry.item_url;
        row.details.classList.remove('disabled');
        row.details.removeAttribute('aria-disabled');
        row.photoUrl = entry.photo_url;
        if (row.photoForm) {
            row.photoForm.action = entry.photo_url;
            row.photoInput.disabled = false;
            row.photoButton.classList.remove('disabled');
        }
        showPhoto(row, entry.photo);
        row.li.classList.remove('is-saving');
        setLabels(row, row.input.value || entry.name);
    }

    function detach(row) {
        row.removed = true;
        row.position = row.li.nextElementSibling;
        if (row.li.contains(document.activeElement)) focusAfter(row.li);
        row.li.remove();
        updateCount();
    }

    function clearPendingDelete(row) {
        row.li.classList.remove('is-pending-delete');
        row.input.readOnly = false;
        row.undoButton.hidden = true;
        row.deleteButton.hidden = false;
    }

    function restore(row, message) {
        row.removed = false;
        clearPendingDelete(row);
        list.insertBefore(row.li, row.position && row.position.isConnected ? row.position : newRow);
        row.input.value = row.saved;
        row.lastSubmitted = row.saved;
        updateCount();
        announce(message);
    }

    function deleteNow(row) {
        const name = row.saved;
        detach(row);
        enqueue(row, async () => {
            try {
                await post(row.deleteUrl);
            } catch (error) {
                // Already deleted elsewhere is as good as deleted here.
                if (error.status !== 404) {
                    restore(row, error.message);
                    return;
                }
            }
            announce(format(texts.deleted, name));
        });
    }

    function commit(row) {
        if (row.removed || row.timer) return;
        const name = normalize(row.input.value);
        if (!name) {
            deleteNow(row);
            return;
        }
        row.input.value = name;
        if (name === row.lastSubmitted) return;
        row.lastSubmitted = name;
        row.li.classList.remove('is-invalid');
        setLabels(row, name);
        enqueue(row, async () => {
            try {
                const result = await post(row.updateUrl, {name});
                row.saved = result.entry.name;
            } catch (error) {
                if (row.lastSubmitted === name) {
                    row.input.value = row.saved;
                    row.lastSubmitted = row.saved;
                    setLabels(row, row.saved);
                }
                row.li.classList.add('is-invalid');
                announce(error.message);
            }
        });
    }

    function scheduleDelete(row) {
        if (row.removed || row.timer) return;
        commit(row);
        if (row.removed) return;
        row.li.classList.add('is-pending-delete');
        row.input.readOnly = true;
        row.deleteButton.hidden = true;
        row.undoButton.hidden = false;
        row.undoButton.focus();
        row.timer = window.setTimeout(() => finishDelete(row), UNDO_DELAY);
        pendingDeletes.add(row);
        announce(format(texts.deleteScheduled, row.input.value));
    }

    function undoDelete(row) {
        if (!row.timer) return;
        window.clearTimeout(row.timer);
        row.timer = null;
        pendingDeletes.delete(row);
        clearPendingDelete(row);
        row.input.focus();
        announce(format(texts.deleteUndone, row.input.value));
    }

    function finishDelete(row) {
        row.timer = null;
        pendingDeletes.delete(row);
        deleteNow(row);
    }

    function setupRow(li) {
        const photoForm = li.querySelector('.location-quick-photo-form');
        const row = {
            li,
            nameForm: li.querySelector('.location-quick-name'),
            deleteForm: li.querySelector('.location-quick-delete-form'),
            photoForm,
            photoInput: photoForm && photoForm.querySelector('[data-quick-photo-input]'),
            photoButton: photoForm && photoForm.querySelector('.location-quick-photo-button'),
            photoLink: li.querySelector('[data-quick-photo-link]'),
            photoImage: li.querySelector('[data-quick-photo-link] img'),
            photoUrl: photoForm ? photoForm.getAttribute('action') : null,
            input: li.querySelector('input[name="name"]'),
            details: li.querySelector('[data-quick-details]'),
            menu: li.querySelector('[data-quick-menu]'),
            deleteButton: li.querySelector('[data-quick-delete]'),
            undoButton: li.querySelector('[data-quick-undo]'),
            updateUrl: li.dataset.updateUrl || null,
            deleteUrl: li.dataset.deleteUrl || null,
            queue: Promise.resolve(),
            timer: null,
            removed: false,
            failed: false,
        };
        row.saved = row.input.value;
        row.lastSubmitted = row.saved;
        li.querySelectorAll('form').forEach(form => form.addEventListener('submit', event => event.preventDefault()));
        if (photoForm) {
            // Uploads as soon as a photo is chosen; the button is only for pages without JavaScript.
            photoForm.querySelector('[data-quick-photo-submit]').hidden = true;
            row.photoInput.addEventListener('change', () => uploadPhoto(row));
        }
        if (window.setupLocationPhotoLink) window.setupLocationPhotoLink(row.photoLink);
        row.input.addEventListener('keydown', event => {
            if (event.isComposing) return;
            if (event.key === 'Enter') {
                event.preventDefault();
                // Moving focus also commits the edit through the blur handler.
                if (normalize(row.input.value)) focusAfter(li);
                else commit(row);
            } else if (event.key === 'Escape' && !row.timer) {
                row.input.value = row.lastSubmitted;
            }
        });
        row.input.addEventListener('blur', () => commit(row));
        row.deleteButton.addEventListener('click', () => scheduleDelete(row));
        row.undoButton.addEventListener('click', () => undoDelete(row));
        return row;
    }

    createForm.addEventListener('submit', event => {
        event.preventDefault();
        const name = normalize(newInput.value);
        if (!name) return;
        newInput.value = '';
        const li = template.content.firstElementChild.cloneNode(true);
        const row = setupRow(li);
        row.input.value = name;
        row.saved = name;
        row.lastSubmitted = name;
        setLabels(row, name);
        list.insertBefore(li, newRow);
        updateCount();
        newInput.focus();
        enqueue(row, async () => {
            try {
                const result = await post(createForm.action, {name});
                applyEntry(row, result.entry);
                announce(format(texts.added, name));
            } catch (error) {
                row.failed = true;
                if (!row.removed) detach(row);
                // Keep what was typed so it can be submitted again.
                if (!newInput.value) newInput.value = row.input.value;
                announce(error.message);
            }
        });
    });

    list.querySelectorAll('[data-quick-item]').forEach(setupRow);
    updateCount();

    // Leaving the page ends the undo window: send outstanding deletions now.
    let deletedOnLeave = false;
    window.addEventListener('pagehide', () => {
        deletedOnLeave = pendingDeletes.size > 0;
        pendingDeletes.forEach(row => {
            window.clearTimeout(row.timer);
            if (!row.deleteUrl || !navigator.sendBeacon) return;
            const body = new FormData();
            body.set('csrfmiddlewaretoken', csrfToken);
            body.set('format', 'json');
            navigator.sendBeacon(row.deleteUrl, body);
        });
        pendingDeletes.clear();
    });
    // A page restored from the back/forward cache would still show those rows.
    window.addEventListener('pageshow', event => {
        if (event.persisted && deletedOnLeave) window.location.reload();
    });
})();
