// Crop and rotate a photo before it is uploaded, like the location overview
// photo. Works on a file input: a new file chosen there, or the photo saved
// before (`existingUrl`), which is fetched only when it is cropped or rotated.
window.PhotoEditor = class PhotoEditor {
    constructor(root) {
        this.root = root;
        this.preview = root.querySelector('[data-photo-preview]');
        this.canvas = root.querySelector('[data-photo-canvas]');
        this.context = this.canvas.getContext('2d');
        this.cropPanel = root.querySelector('[data-photo-crop]');
        this.cropToggle = root.querySelector('[data-photo-crop-toggle]');
        this.rotateButton = root.querySelector('[data-photo-rotate]');
        this.status = root.querySelector('[data-photo-status]');
        this.sliders = [...root.querySelectorAll('[data-crop-edge]')];
        this.libraryInput = root.querySelector('[data-photo-library-input]');
        this.onInputChange = () => this.load(this.input.files[0]);
        this.reset();

        root.querySelector('[data-photo-library]').addEventListener('click', () => this.libraryInput.click());
        this.libraryInput.addEventListener('change', () => {
            const file = this.libraryInput.files[0];
            this.libraryInput.value = '';
            if (file && this.input) {
                PhotoEditor.setFile(this.input, file);
                this.load(file);
            }
        });
        this.cropToggle.addEventListener('click', async () => {
            if (await this.loadExisting()) this.setCropEnabled(!this.cropEnabled);
        });
        this.rotateButton.addEventListener('click', async () => {
            if (!await this.loadExisting()) return;
            this.quarterTurns = (this.quarterTurns + 1) % 4;
            this.resetCrop();
            this.updatePreview();
            this.say('rotated');
        });
        root.querySelector('[data-photo-reset-crop]').addEventListener('click', () => this.resetCrop());
        this.sliders.forEach(slider => slider.addEventListener('input', () => {
            const edge = slider.dataset.cropEdge;
            const bounds = {
                left: [0, this.crop.right - 1], right: [this.crop.left + 1, 100],
                top: [0, this.crop.bottom - 1], bottom: [this.crop.top + 1, 100],
            };
            this.crop[edge] = Math.max(bounds[edge][0], Math.min(bounds[edge][1], Number(slider.value)));
            this.drawCrop();
        }));
        this.canvas.addEventListener('pointerdown', event => {
            if (!this.image || !event.isPrimary || event.button !== 0) return;
            this.canvas.setPointerCapture(event.pointerId);
            this.dragStart = {...this.pointer(event), pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY, moved: false};
            event.preventDefault();
        });
        this.canvas.addEventListener('pointermove', event => this.drag(event));
        this.canvas.addEventListener('pointerup', event => {
            if (!this.dragStart || this.dragStart.pointerId !== event.pointerId) return;
            this.drag(event);
            this.dragStart = null;
            this.canvas.releasePointerCapture(event.pointerId);
        });
        this.canvas.addEventListener('pointercancel', () => { this.dragStart = null; });
    }

    static setFile(input, file) {
        const transfer = new DataTransfer();
        if (file) transfer.items.add(file);
        input.files = transfer.files;
    }

    // Edit the photo of `input`; `existingUrl` is the saved photo, if any.
    attach(input, existingUrl) {
        this.detach();
        this.input = input;
        this.existingUrl = existingUrl || '';
        input.addEventListener('change', this.onInputChange);
        if (input.files[0]) this.load(input.files[0]);
        else this.showPreview(this.existingUrl);
        this.updateBusy();
    }

    detach() {
        if (this.input) this.input.removeEventListener('change', this.onInputChange);
        this.input = null;
        this.reset();
    }

    reset() {
        this.generation = (this.generation || 0) + 1;
        if (this.photoURL) URL.revokeObjectURL(this.photoURL);
        this.photoURL = null;
        this.image = null;
        this.file = null;
        this.editingExisting = false;
        this.loading = false;
        this.quarterTurns = 0;
        this.cropEnabled = false;
        this.cropPanel.hidden = true;
        this.cropToggle.setAttribute('aria-expanded', 'false');
        this.crop = {left: 0, top: 0, right: 100, bottom: 100};
        this.showPreview('');
        this.say(null);
        this.updateBusy();
    }

    say(key, error = false) {
        this.status.textContent = key ? this.status.dataset[key] : '';
        this.status.classList.toggle('text-danger', error);
    }

    showPreview(url) {
        if (url) this.preview.src = url;
        else this.preview.removeAttribute('src');
        this.preview.hidden = !url || this.cropEnabled;
    }

    updateBusy() {
        const unavailable = this.loading || !this.context || (!this.image && !this.existingUrl);
        this.cropToggle.disabled = unavailable;
        this.rotateButton.disabled = unavailable;
    }

    async load(file, {existing = false} = {}) {
        if (!file) return;
        const generation = ++this.generation;
        if (this.photoURL) URL.revokeObjectURL(this.photoURL);
        this.photoURL = URL.createObjectURL(file);
        this.loading = true;
        this.updateBusy();
        this.say('loading');
        const image = new Image();
        try {
            await new Promise((resolve, reject) => {
                image.onload = resolve;
                image.onerror = reject;
                image.src = this.photoURL;
            });
            if (generation !== this.generation) return;
            if (!image.naturalWidth || !image.naturalHeight) throw new Error('Empty image');
            this.image = image;
            this.file = file;
            this.editingExisting = existing;
            this.quarterTurns = 0;
            this.crop = {left: 0, top: 0, right: 100, bottom: 100};
            this.updatePreview();
            this.say(existing ? 'editing' : 'ready');
        } catch {
            if (generation !== this.generation) return;
            this.image = this.file = null;
            if (!existing && this.input) PhotoEditor.setFile(this.input, null);
            this.showPreview(this.existingUrl);
            this.say('invalid', true);
        } finally {
            if (generation === this.generation) {
                this.loading = false;
                this.updateBusy();
            }
        }
    }

    async loadExisting() {
        // Fetching (rather than drawing the <img>) keeps the canvas exportable.
        if (this.image) return true;
        if (!this.existingUrl || this.loading) return false;
        try {
            const response = await fetch(this.existingUrl, {credentials: 'same-origin'});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const blob = await response.blob();
            // Saved names start with an upload timestamp; the server adds a new one.
            const saved = new URL(this.existingUrl, window.location.href).pathname.split('/').pop() || 'photo.jpg';
            const name = decodeURIComponent(saved).replace(/^\d{4}-\d\d-\d\dT[\d:.]+_/, '');
            await this.load(new File([blob], name, {type: blob.type}), {existing: true});
        } catch {
            this.say('existingError', true);
        }
        return Boolean(this.image);
    }

    setCropEnabled(enabled) {
        this.cropEnabled = enabled;
        this.cropPanel.hidden = !enabled;
        this.cropToggle.setAttribute('aria-expanded', String(enabled));
        this.preview.hidden = enabled || !this.preview.getAttribute('src');
        if (enabled) this.drawCrop();
    }

    dimensions() {
        return this.quarterTurns % 2
            ? {width: this.image.naturalHeight, height: this.image.naturalWidth}
            : {width: this.image.naturalWidth, height: this.image.naturalHeight};
    }

    drawImage(target, width, height) {
        target.save();
        if (this.quarterTurns === 1) target.translate(width, 0);
        else if (this.quarterTurns === 2) target.translate(width, height);
        else if (this.quarterTurns === 3) target.translate(0, height);
        target.rotate(this.quarterTurns * Math.PI / 2);
        const sideways = this.quarterTurns % 2;
        target.drawImage(this.image, 0, 0, sideways ? height : width, sideways ? width : height);
        target.restore();
    }

    updatePreview() {
        const {width, height} = this.dimensions();
        // Keep the interactive canvas small; export uses the original pixels.
        const scale = Math.min(1, 960 / width, 960 / height);
        this.canvas.width = Math.max(1, Math.round(width * scale));
        this.canvas.height = Math.max(1, Math.round(height * scale));
        if (this.context) {
            this.drawImage(this.context, this.canvas.width, this.canvas.height);
            this.showPreview(this.quarterTurns ? this.canvas.toDataURL('image/png') : this.photoURL);
        }
        this.drawCrop();
    }

    resetCrop() {
        this.crop = {left: 0, top: 0, right: 100, bottom: 100};
        this.dragStart = null;
        this.drawCrop();
    }

    drawCrop() {
        if (!this.image || !this.context) return;
        const {width, height} = this.canvas;
        const [left, top, right, bottom] = [
            this.crop.left * width / 100, this.crop.top * height / 100,
            this.crop.right * width / 100, this.crop.bottom * height / 100,
        ];
        const context = this.context;
        context.clearRect(0, 0, width, height);
        this.drawImage(context, width, height);
        context.fillStyle = 'rgba(0, 0, 0, .55)';
        context.fillRect(0, 0, width, top);
        context.fillRect(0, bottom, width, height - bottom);
        context.fillRect(0, top, left, bottom - top);
        context.fillRect(right, top, width - right, bottom - top);
        context.strokeStyle = '#ffffff';
        context.lineWidth = 3;
        context.strokeRect(left, top, right - left, bottom - top);
        this.sliders.forEach(slider => { slider.value = this.crop[slider.dataset.cropEdge]; });
    }

    pointer(event) {
        const bounds = this.canvas.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(100, (event.clientX - bounds.left) / bounds.width * 100)),
            y: Math.max(0, Math.min(100, (event.clientY - bounds.top) / bounds.height * 100)),
        };
    }

    drag(event) {
        const start = this.dragStart;
        if (!start || start.pointerId !== event.pointerId) return;
        if (!start.moved && Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY) < 5) return;
        start.moved = true;
        const point = this.pointer(event);
        this.crop = {
            left: Math.min(start.x, point.x, 99), top: Math.min(start.y, point.y, 99),
            right: Math.max(start.x, point.x, 1), bottom: Math.max(start.y, point.y, 1),
        };
        this.crop.right = Math.max(this.crop.right, this.crop.left + 1);
        this.crop.bottom = Math.max(this.crop.bottom, this.crop.top + 1);
        this.drawCrop();
    }

    edited() {
        const cropped = this.cropEnabled && (this.crop.left > 0 || this.crop.top > 0 || this.crop.right < 100 || this.crop.bottom < 100);
        return Boolean(this.image) && (Boolean(this.quarterTurns) || cropped);
    }

    // The file to put into the input, or null when the input already holds the right one.
    async result() {
        if (!this.image) return null;
        const webSafe = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(this.file.type);
        // An unchanged saved photo is not uploaded again; other formats (e.g. HEIC) are converted.
        if (!this.edited() && (this.editingExisting || webSafe)) return null;
        const bounds = this.cropEnabled ? this.crop : {left: 0, top: 0, right: 100, bottom: 100};
        const size = this.dimensions();
        const left = Math.min(size.width - 1, Math.round(bounds.left * size.width / 100));
        const top = Math.min(size.height - 1, Math.round(bounds.top * size.height / 100));
        const width = Math.min(size.width - left, Math.max(1, Math.round((bounds.right - bounds.left) * size.width / 100)));
        const height = Math.min(size.height - top, Math.max(1, Math.round((bounds.bottom - bounds.top) * size.height / 100)));
        // Bound export memory for high-resolution phone cameras.
        const scale = Math.min(1, 4096 / width, 4096 / height);
        const output = document.createElement('canvas');
        output.width = Math.max(1, Math.round(width * scale));
        output.height = Math.max(1, Math.round(height * scale));
        const context = output.getContext('2d');
        if (!context) throw new Error('Canvas unavailable');
        // JPEG has no transparency, so transparent areas receive a white backing.
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, output.width, output.height);
        if (this.quarterTurns) {
            context.scale(output.width / width, output.height / height);
            context.translate(-left, -top);
            this.drawImage(context, size.width, size.height);
        } else {
            context.drawImage(this.image, left, top, width, height, 0, 0, output.width, output.height);
        }
        try {
            const blob = await new Promise((resolve, reject) => {
                output.toBlob(result => result ? resolve(result) : reject(new Error('Image encoding failed')), 'image/jpeg', .92);
            });
            const suffix = this.cropEnabled ? 'cropped' : this.quarterTurns ? 'rotated' : 'photo';
            return new File([blob], `${this.file.name.replace(/\.[^.]+$/, '')}-${suffix}.jpg`, {type: 'image/jpeg'});
        } finally {
            output.width = output.height = 0;
        }
    }
};
