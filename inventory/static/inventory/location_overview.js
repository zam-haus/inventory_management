(() => {
    const editor = document.getElementById('location-overview-editor');
    if (!editor || typeof bootstrap === 'undefined' || !bootstrap.Modal) return;

    const form = editor.querySelector('form');
    const photoInput = form.elements.overview_photo;
    const libraryInput = editor.querySelector('[data-overview-library-input]');
    const removeInput = form.elements.remove_photo;
    const removeControl = editor.querySelector('[data-overview-remove]');
    const preview = editor.querySelector('[data-overview-preview]');
    const existingPhoto = preview.getAttribute('src') || '';
    const cropToggle = editor.querySelector('[data-overview-crop-toggle]');
    const rotateButton = editor.querySelector('[data-overview-rotate]');
    const cropPanel = editor.querySelector('.location-overview-crop');
    const canvas = editor.querySelector('[data-overview-canvas]');
    const context = canvas.getContext('2d');
    const sliders = [...editor.querySelectorAll('[data-crop-edge]')];
    const save = editor.querySelector('[data-overview-save]');
    const errors = editor.querySelector('[data-overview-errors]');
    const status = editor.querySelector('[data-overview-photo-status]');
    const counter = editor.querySelector('[data-overview-count]');
    let selectedFile = null;
    let sourceImage = null;
    let photoURL = null;
    let photoGeneration = 0;
    let imageLoading = false;
    let submitting = false;
    let cropEnabled = false;
    let quarterTurns = 0;
    let dragStart = null;
    let crop = {left: 0, top: 0, right: 100, bottom: 100};

    editor.classList.add('modal', 'fade');
    editor.querySelectorAll('[data-overview-enhanced]').forEach(element => { element.hidden = false; });
    const modal = new bootstrap.Modal(editor);

    function updateCounter() {
        counter.textContent = `${Array.from(form.elements.summary.value).length} / 50`;
    }

    function updateBusy() {
        save.disabled = submitting || imageLoading;
        form.setAttribute('aria-busy', String(submitting || imageLoading));
        editor.querySelectorAll('[data-bs-dismiss="modal"], input, [data-overview-library], [data-overview-reset-crop]').forEach(element => {
            element.disabled = submitting;
        });
        cropToggle.disabled = submitting || imageLoading || !sourceImage || !context;
        rotateButton.disabled = cropToggle.disabled;
    }

    function clearErrors() {
        errors.replaceChildren();
        errors.hidden = true;
        editor.querySelectorAll('[data-overview-field-errors]').forEach(element => { element.replaceChildren(); });
        form.querySelectorAll('[aria-invalid]').forEach(element => { element.removeAttribute('aria-invalid'); });
    }

    function showError(message) {
        errors.textContent = message;
        errors.hidden = false;
        errors.tabIndex = -1;
        errors.focus();
    }

    function setCropEnabled(enabled) {
        cropEnabled = enabled;
        cropPanel.hidden = !enabled;
        cropToggle.setAttribute('aria-expanded', String(enabled));
        preview.hidden = enabled || !preview.getAttribute('src') || removeInput.checked;
        if (enabled) drawCrop();
    }

    function orientedDimensions() {
        return quarterTurns % 2
            ? {width: sourceImage.naturalHeight, height: sourceImage.naturalWidth}
            : {width: sourceImage.naturalWidth, height: sourceImage.naturalHeight};
    }

    function drawOrientedImage(target, width, height) {
        target.save();
        if (quarterTurns === 1) target.translate(width, 0);
        else if (quarterTurns === 2) target.translate(width, height);
        else if (quarterTurns === 3) target.translate(0, height);
        target.rotate(quarterTurns * Math.PI / 2);
        target.drawImage(sourceImage, 0, 0, quarterTurns % 2 ? height : width, quarterTurns % 2 ? width : height);
        target.restore();
    }

    function updatePhotoPreview() {
        const dimensions = orientedDimensions();
        // Keep the interactive canvas small; export uses the original pixels.
        const scale = Math.min(1, 960 / dimensions.width, 960 / dimensions.height);
        canvas.width = Math.max(1, Math.round(dimensions.width * scale));
        canvas.height = Math.max(1, Math.round(dimensions.height * scale));
        if (context) {
            drawOrientedImage(context, canvas.width, canvas.height);
            preview.src = quarterTurns ? canvas.toDataURL('image/png') : photoURL;
        }
        drawCrop();
    }

    function drawCrop() {
        if (!sourceImage || !context) return;
        const width = canvas.width;
        const height = canvas.height;
        const left = crop.left * width / 100;
        const top = crop.top * height / 100;
        const right = crop.right * width / 100;
        const bottom = crop.bottom * height / 100;
        context.clearRect(0, 0, width, height);
        drawOrientedImage(context, width, height);
        context.fillStyle = 'rgba(0, 0, 0, .55)';
        context.fillRect(0, 0, width, top);
        context.fillRect(0, bottom, width, height - bottom);
        context.fillRect(0, top, left, bottom - top);
        context.fillRect(right, top, width - right, bottom - top);
        context.strokeStyle = '#ffffff';
        context.lineWidth = 3;
        context.strokeRect(left, top, right - left, bottom - top);
        sliders.forEach(slider => { slider.value = crop[slider.dataset.cropEdge]; });
    }

    function resetCrop() {
        crop = {left: 0, top: 0, right: 100, bottom: 100};
        dragStart = null;
        drawCrop();
    }

    function clearNewPhoto() {
        photoGeneration += 1;
        sourceImage = null;
        quarterTurns = 0;
        selectedFile = null;
        imageLoading = false;
        photoInput.value = '';
        libraryInput.value = '';
        if (photoURL) URL.revokeObjectURL(photoURL);
        photoURL = null;
        if (existingPhoto) preview.src = existingPhoto;
        else preview.removeAttribute('src');
        setCropEnabled(false);
        resetCrop();
        removeControl.hidden = !existingPhoto;
        status.textContent = '';
        status.classList.remove('text-danger');
        updateBusy();
    }

    async function selectPhoto(file) {
        // Cancelling the native picker keeps the previously chosen photo.
        if (!file) return;
        clearNewPhoto();
        const generation = photoGeneration;
        imageLoading = true;
        updateBusy();
        status.textContent = status.dataset.loading;
        const url = URL.createObjectURL(file);
        photoURL = url;
        const image = new Image();
        try {
            await new Promise((resolve, reject) => {
                image.onload = resolve;
                image.onerror = reject;
                image.src = url;
            });
            if (generation !== photoGeneration) return;
            if (!image.naturalWidth || !image.naturalHeight) throw new Error('Empty image');
            sourceImage = image;
            selectedFile = file;
            removeInput.checked = false;
            removeControl.hidden = false;
            preview.src = url;
            preview.hidden = false;
            updatePhotoPreview();
            resetCrop();
            status.textContent = status.dataset.ready;
        } catch {
            if (generation !== photoGeneration) return;
            clearNewPhoto();
            status.textContent = status.dataset.invalid;
            status.classList.add('text-danger');
        } finally {
            if (generation === photoGeneration) {
                imageLoading = false;
                updateBusy();
            }
        }
    }

    function pointerPosition(event) {
        const bounds = canvas.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(100, (event.clientX - bounds.left) / bounds.width * 100)),
            y: Math.max(0, Math.min(100, (event.clientY - bounds.top) / bounds.height * 100)),
        };
    }

    function updateDrag(event) {
        if (!dragStart || dragStart.pointerId !== event.pointerId) return;
        const point = pointerPosition(event);
        if (!dragStart.moved && Math.hypot(event.clientX - dragStart.clientX, event.clientY - dragStart.clientY) < 5) return;
        dragStart.moved = true;
        crop = {
            left: Math.min(dragStart.x, point.x, 99),
            top: Math.min(dragStart.y, point.y, 99),
            right: Math.max(dragStart.x, point.x, 1),
            bottom: Math.max(dragStart.y, point.y, 1),
        };
        crop.right = Math.max(crop.right, crop.left + 1);
        crop.bottom = Math.max(crop.bottom, crop.top + 1);
        drawCrop();
    }

    canvas.addEventListener('pointerdown', event => {
        if (submitting || !sourceImage || !event.isPrimary || event.button !== 0) return;
        canvas.setPointerCapture(event.pointerId);
        dragStart = {...pointerPosition(event), pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY, moved: false};
        event.preventDefault();
    });
    canvas.addEventListener('pointermove', updateDrag);
    canvas.addEventListener('pointerup', event => {
        if (!dragStart || dragStart.pointerId !== event.pointerId) return;
        updateDrag(event);
        dragStart = null;
        canvas.releasePointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointercancel', () => { dragStart = null; });
    sliders.forEach(slider => {
        slider.addEventListener('input', () => {
            const edge = slider.dataset.cropEdge;
            const value = Number(slider.value);
            const bounds = {
                left: [0, crop.right - 1], right: [crop.left + 1, 100],
                top: [0, crop.bottom - 1], bottom: [crop.top + 1, 100],
            };
            crop[edge] = Math.max(bounds[edge][0], Math.min(bounds[edge][1], value));
            drawCrop();
        });
    });

    async function photoToUpload() {
        // Native cameras may supply HEIC/HEIF; encode decoded images into a
        // broadly supported format when the original cannot be uploaded as-is.
        if (!cropEnabled && !quarterTurns && ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(selectedFile.type)) return selectedFile;
        const output = document.createElement('canvas');
        const bounds = cropEnabled ? crop : {left: 0, top: 0, right: 100, bottom: 100};
        const dimensions = orientedDimensions();
        const left = Math.min(dimensions.width - 1, Math.round(bounds.left * dimensions.width / 100));
        const top = Math.min(dimensions.height - 1, Math.round(bounds.top * dimensions.height / 100));
        const width = Math.min(dimensions.width - left, Math.max(1, Math.round((bounds.right - bounds.left) * dimensions.width / 100)));
        const height = Math.min(dimensions.height - top, Math.max(1, Math.round((bounds.bottom - bounds.top) * dimensions.height / 100)));
        // Bound export memory for high-resolution phone cameras, independently
        // of the smaller interactive preview canvas.
        const scale = Math.min(1, 4096 / width, 4096 / height);
        output.width = Math.max(1, Math.round(width * scale));
        output.height = Math.max(1, Math.round(height * scale));
        const outputContext = output.getContext('2d');
        if (!outputContext) throw new Error('Canvas unavailable');
        // JPEG has no transparency, so transparent areas receive a white backing.
        outputContext.fillStyle = '#ffffff';
        outputContext.fillRect(0, 0, output.width, output.height);
        if (quarterTurns) {
            // Crop in the displayed orientation, without allocating a second
            // full-resolution canvas for the rotated camera photo.
            outputContext.scale(output.width / width, output.height / height);
            outputContext.translate(-left, -top);
            drawOrientedImage(outputContext, dimensions.width, dimensions.height);
        } else {
            outputContext.drawImage(sourceImage, left, top, width, height, 0, 0, output.width, output.height);
        }
        try {
            const blob = await new Promise((resolve, reject) => {
                output.toBlob(result => result ? resolve(result) : reject(new Error('Image encoding failed')), 'image/jpeg', .92);
            });
            const suffix = cropEnabled ? 'cropped' : quarterTurns ? 'rotated' : 'overview';
            return new File([blob], `${selectedFile.name.replace(/\.[^.]+$/, '')}-${suffix}.jpg`, {type: 'image/jpeg'});
        } finally {
            output.width = 0;
            output.height = 0;
        }
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (submitting || imageLoading || !form.reportValidity()) return;
        clearErrors();
        // Disabled controls are excluded from FormData, so collect them first.
        const data = new FormData(form);
        data.delete('overview_photo');
        submitting = true;
        updateBusy();
        let phase = 'photo';
        try {
            if (selectedFile && !removeInput.checked) {
                const photo = await photoToUpload();
                data.set('overview_photo', photo, photo.name);
            }
            phase = 'request';
            const response = await fetch(form.action, {
                method: 'POST', body: data, headers: {Accept: 'application/json'}, credentials: 'same-origin',
            });
            const result = await response.json();
            if (response.ok && result.ok) {
                window.location.assign(result.url);
                return;
            }
            Object.entries(result.errors || {}).forEach(([name, messages]) => {
                const target = [...editor.querySelectorAll('[data-overview-field-errors]')].find(element => element.dataset.overviewFieldErrors === name);
                const message = messages.map(error => error.message || String(error)).join(' ');
                if (target) {
                    target.textContent = message;
                    if (form.elements[name]) form.elements[name].setAttribute('aria-invalid', 'true');
                } else {
                    const paragraph = document.createElement('p');
                    paragraph.textContent = message;
                    errors.append(paragraph);
                }
            });
            if (errors.childElementCount) {
                errors.hidden = false;
                errors.tabIndex = -1;
                errors.focus();
            } else showError(status.dataset.validationError);
        } catch {
            showError(phase === 'photo' ? status.dataset.photoError : status.dataset.networkError);
        } finally {
            submitting = false;
            updateBusy();
        }
    });

    photoInput.addEventListener('change', () => { selectPhoto(photoInput.files[0]); });
    libraryInput.addEventListener('change', () => { selectPhoto(libraryInput.files[0]); });
    editor.querySelector('[data-overview-library]').addEventListener('click', () => { libraryInput.click(); });
    cropToggle.addEventListener('click', () => { setCropEnabled(!cropEnabled); });
    rotateButton.addEventListener('click', () => {
        if (submitting || imageLoading || !sourceImage || !context) return;
        quarterTurns = (quarterTurns + 1) % 4;
        resetCrop();
        updatePhotoPreview();
        status.textContent = status.dataset.rotated;
    });
    editor.querySelector('[data-overview-reset-crop]').addEventListener('click', () => { resetCrop(); });
    removeInput.addEventListener('change', () => {
        if (removeInput.checked) clearNewPhoto();
        preview.hidden = removeInput.checked || !preview.getAttribute('src');
    });
    form.elements.summary.addEventListener('input', updateCounter);
    document.querySelectorAll('[data-overview-open]').forEach(trigger => {
        trigger.addEventListener('click', event => {
            event.preventDefault();
            modal.show(trigger);
        });
    });
    editor.addEventListener('shown.bs.modal', () => { form.elements.summary.focus(); });
    editor.addEventListener('hide.bs.modal', event => {
        // A confirmed save cannot be cancelled once it has reached the server.
        if (submitting) event.preventDefault();
    });
    editor.addEventListener('hidden.bs.modal', () => {
        form.reset();
        clearNewPhoto();
        clearErrors();
        updateCounter();
    });
    updateCounter();
    preview.hidden = removeInput.checked || !existingPhoto;
    if (editor.dataset.open === 'true' || window.location.hash === '#location-overview-editor') modal.show();
})();
