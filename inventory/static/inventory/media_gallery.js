// Photos and files of item and unique item forms: a horizontal gallery of what
// is attached, plus an "add" tile. Adding, replacing, editing and deleting
// happen in a modal that edits the formset row; everything is saved with the
// form. Without JavaScript the formset rows stay as they are.
(() => {
    const modalElement = document.getElementById('media-modal');
    const containers = [...document.querySelectorAll('[data-formset][data-media]')];
    if (!modalElement || !containers.length || typeof bootstrap === 'undefined' || !window.PhotoEditor) return;

    const text = modalElement.dataset;
    const modal = new bootstrap.Modal(modalElement);
    const slot = modalElement.querySelector('[data-media-slot]');
    const title = modalElement.querySelector('[data-media-title]');
    const deleteButton = modalElement.querySelector('[data-media-delete]');
    const restoreButton = modalElement.querySelector('[data-media-restore]');
    const applyButton = modalElement.querySelector('[data-media-apply]');
    const tools = modalElement.querySelector('[data-photo-tools]');
    const toolsHome = document.createComment('photo tools');
    tools.before(toolsHome);
    const editor = new PhotoEditor(tools);
    const FILE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">'
        + '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
        + '<path d="M9 13h6M9 17h6"/></svg>';
    let current = null;

    const field = (row, name) => row.querySelector(`[name$="-${name}"]`);
    const inputs = row => [...row.querySelectorAll('input, select, textarea')].filter(input => input.type !== 'hidden');

    function snapshot(row) {
        return inputs(row).map(input => ({input, value: input.value, checked: input.checked, files: input.files}));
    }

    function restore(state) {
        state.forEach(({input, value, checked, files}) => {
            if (input.type === 'file') input.files = files;
            else if (input.type === 'checkbox' || input.type === 'radio') input.checked = checked;
            else input.value = value;
        });
    }

    function differs(state) {
        return state.some(({input, value, checked, files}) => {
            if (input.type === 'file') return input.files.length !== files.length || input.files[0] !== files[0];
            if (input.type === 'checkbox' || input.type === 'radio') return input.checked !== checked;
            return input.value !== value;
        });
    }

    class Gallery {
        constructor(container) {
            this.container = container;
            this.kind = container.dataset.media;
            this.prefix = container.dataset.formset;
            this.canAdd = 'canAdd' in container.dataset;
            this.total = container.querySelector(`#id_${this.prefix}-TOTAL_FORMS`);
            const rows = this.rows();
            // A pristine empty row to copy for each new photo or file.
            const blank = rows.find(row => !this.saved(row));
            this.template = blank ? blank.cloneNode(true) : null;
            rows.forEach(row => this.prepare(row));
            this.list = document.createElement('div');
            this.list.className = 'media-gallery';
            this.list.setAttribute('role', 'list');
            container.querySelector('legend').after(this.list);
            this.render();
        }

        rows() {
            return [...this.container.querySelectorAll('.formset-row')];
        }

        saved(row) {
            return 'saved' in row.querySelector('[data-media-info]').dataset;
        }

        prepare(row) {
            row.initialState = snapshot(row);
            row.hidden = true;
            row.querySelectorAll('[data-media-fallback], [data-media-delete-field]').forEach(element => { element.hidden = true; });
        }

        fileInput(row) {
            return field(row, this.kind === 'photo' ? 'image' : 'file');
        }

        state(row) {
            const info = row.querySelector('[data-media-info]').dataset;
            const chosen = this.fileInput(row)?.files[0] || null;
            const description = field(row, 'description')?.value.trim() || '';
            const hasError = Boolean(row.querySelector('.is-invalid, .invalid-feedback, .errorlist'));
            const saved = this.saved(row);
            return {
                info, chosen, saved, hasError,
                shown: saved || chosen || hasError,
                name: description || chosen?.name || info.name || '',
                deleted: Boolean(field(row, 'DELETE')?.checked),
                changed: saved && differs(row.initialState),
            };
        }

        badges(row, state) {
            const badges = [];
            if (field(row, 'is_primary')?.checked) badges.push(['primary', `★ ${text.primary}`]);
            const select = field(row, 'unique_item');
            if (select?.value) badges.push(['level', select.selectedOptions[0]?.textContent.trim()]);
            const level = row.querySelector('input[name$="-level"]:checked');
            if (level?.value === 'item') badges.push(['general', text.general]);
            if (field(row, 'internal')?.checked) badges.push(['internal', text.internal]);
            if (state.hasError) badges.push(['error', text.error]);
            else if (state.deleted) badges.push(['deleted', text.deleted]);
            else if (!state.saved) badges.push(['new', text.new]);
            else if (state.changed) badges.push(['changed', text.changed]);
            return badges;
        }

        thumbnail(row, state) {
            const frame = document.createElement('span');
            frame.className = 'media-tile-thumb';
            if (this.kind === 'photo' && (state.chosen || state.info.thumb)) {
                const image = document.createElement('img');
                if (state.chosen) {
                    if (row.previewFile !== state.chosen) {
                        if (row.previewURL) URL.revokeObjectURL(row.previewURL);
                        row.previewURL = URL.createObjectURL(state.chosen);
                        row.previewFile = state.chosen;
                    }
                    image.src = row.previewURL;
                } else image.src = state.info.thumb;
                image.alt = '';
                frame.append(image);
            } else frame.innerHTML = FILE_ICON;
            return frame;
        }

        render() {
            this.list.replaceChildren();
            this.rows().forEach(row => {
                const state = this.state(row);
                if (!state.shown) return;
                const tile = document.createElement('button');
                tile.type = 'button';
                tile.className = 'media-tile';
                tile.setAttribute('role', 'listitem');
                tile.classList.toggle('is-deleted', state.deleted);
                tile.classList.toggle('has-error', state.hasError);
                const name = document.createElement('span');
                name.className = 'media-tile-name';
                name.textContent = state.name;
                const badges = document.createElement('span');
                badges.className = 'media-tile-badges';
                this.badges(row, state).forEach(([kind, label]) => {
                    const badge = document.createElement('span');
                    badge.className = `media-badge media-badge-${kind}`;
                    badge.textContent = label;
                    badges.append(badge);
                });
                tile.append(this.thumbnail(row, state), name, badges);
                tile.setAttribute('aria-label', [state.name, ...[...badges.children].map(badge => badge.textContent)].filter(Boolean).join(', '));
                tile.addEventListener('click', () => open(this, row, false));
                this.list.append(tile);
            });
            if (this.canAdd && this.template) {
                const add = document.createElement('button');
                add.type = 'button';
                add.className = 'media-tile media-tile-add';
                add.setAttribute('role', 'listitem');
                add.innerHTML = '<span class="media-tile-plus" aria-hidden="true">+</span>';
                add.append(this.kind === 'photo' ? text.newPhoto : text.newFile);
                add.addEventListener('click', () => open(this, this.newRow(), true));
                this.list.append(add);
            }
        }

        newRow() {
            // Reuse an untouched empty row, or copy the pristine one.
            const unused = this.rows().find(row => !this.state(row).shown && !differs(row.initialState));
            if (unused) return unused;
            const index = Number(this.total.value);
            const pattern = new RegExp(`${this.prefix}-\\d+-`, 'g');
            const row = this.template.cloneNode(true);
            row.querySelectorAll('*').forEach(element => {
                ['id', 'name', 'for', 'list', 'aria-describedby'].forEach(attribute => {
                    const value = element.getAttribute(attribute);
                    if (value) element.setAttribute(attribute, value.replace(pattern, `${this.prefix}-${index}-`));
                });
            });
            this.total.value = index + 1;
            this.rows().at(-1).after(row);
            this.prepare(row);
            return row;
        }
    }

    function open(gallery, row, isNew) {
        const state = gallery.state(row);
        current = {gallery, row, isNew, state: snapshot(row), applied: false, placeholder: document.createComment('media row')};
        row.before(current.placeholder);
        slot.append(row);
        row.hidden = false;
        const kind = gallery.kind === 'photo' ? 'Photo' : 'File';
        title.textContent = text[(isNew ? 'new' : 'edit') + kind];
        const deletion = field(row, 'DELETE');
        const removable = state.saved ? Boolean(deletion) : !isNew;
        deleteButton.hidden = !removable || state.deleted;
        deleteButton.textContent = state.saved ? deleteButton.dataset.deleteLabel : deleteButton.dataset.removeLabel;
        restoreButton.hidden = !state.deleted;
        tools.hidden = gallery.kind !== 'photo';
        if (gallery.kind === 'photo') {
            // Preview, crop and rotate right below where the photo is chosen.
            const input = gallery.fileInput(row);
            (input.closest('.input-group') || input).after(tools);
            editor.attach(input, state.info.image);
        }
        modal.show();
    }

    async function apply() {
        if (!current) return;
        applyButton.disabled = true;
        try {
            if (current.gallery.kind === 'photo') {
                const file = await editor.result();
                if (file) PhotoEditor.setFile(current.gallery.fileInput(current.row), file);
            }
            current.applied = true;
            modal.hide();
        } catch {
            editor.say('photoError', true);
        } finally {
            applyButton.disabled = false;
        }
    }

    deleteButton.addEventListener('click', () => {
        if (!current) return;
        const deletion = field(current.row, 'DELETE');
        if (deletion && current.gallery.saved(current.row)) deletion.checked = true;
        else restore(current.row.initialState);  // a new photo or file is simply dropped
        current.applied = true;
        modal.hide();
    });
    restoreButton.addEventListener('click', () => {
        const deletion = current && field(current.row, 'DELETE');
        if (deletion) deletion.checked = false;
        restoreButton.hidden = true;
        deleteButton.hidden = false;
    });
    applyButton.addEventListener('click', apply);
    // Enter in a field of the modal applies it instead of submitting the whole form.
    modalElement.addEventListener('keydown', event => {
        if (event.key === 'Enter' && event.target.matches('input:not([type=file]), select')) {
            event.preventDefault();
            apply();
        }
    });
    modalElement.addEventListener('hidden.bs.modal', () => {
        if (!current) return;
        const {gallery, row, state, applied, placeholder} = current;
        if (!applied) restore(state);
        editor.detach();
        toolsHome.after(tools);
        row.hidden = true;
        placeholder.replaceWith(row);
        current = null;
        gallery.render();
    });

    const galleries = containers.map(container => new Gallery(container));
    // After a failed save, the first photo or file with an error is opened.
    for (const gallery of galleries) {
        const row = gallery.rows().find(candidate => gallery.state(candidate).hasError);
        if (row) {
            open(gallery, row, false);
            break;
        }
    }
})();
