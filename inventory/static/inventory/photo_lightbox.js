// Photo lightbox on a native <dialog>: Escape, focus trapping and the page
// behind it are handled by the browser. Every photo load belongs to one
// "generation", so closing or browsing never waits for the network and late
// responses of a slow connection are ignored instead of reopening anything.
//
// setupPhotoLightbox(links, {className, labels, onShow}) makes the links one
// group to browse. `labels` holds gallery, close, previous, next, error, retry
// and loading texts; `onShow(viewer, link)` runs once a photo is displayed and
// may add elements to `viewer.figure`.
(() => {
    let viewer = null;

    function createViewer() {
        const dialog = document.createElement('dialog');
        dialog.className = 'photo-lightbox';
        dialog.innerHTML = `
            <p class="photo-lightbox-counter" aria-live="polite"></p>
            <div class="photo-lightbox-stage">
                <div class="photo-lightbox-figure">
                    <img class="photo-lightbox-image" alt="" draggable="false" hidden>
                </div>
                <div class="photo-lightbox-loading" role="status" hidden><span class="photo-lightbox-spinner" aria-hidden="true"></span><span class="visually-hidden"></span></div>
                <div class="photo-lightbox-message" role="alert" hidden><p></p><button type="button" class="btn btn-light photo-lightbox-retry"></button></div>
            </div>
            <button type="button" class="photo-lightbox-button photo-lightbox-prev"><span aria-hidden="true">❮</span></button>
            <button type="button" class="photo-lightbox-button photo-lightbox-next"><span aria-hidden="true">❯</span></button>
            <button type="button" class="photo-lightbox-button photo-lightbox-close"><span aria-hidden="true">×</span></button>`;
        document.body.append(dialog);
        const q = selector => dialog.querySelector(selector);
        const self = {
            dialog, figure: q('.photo-lightbox-figure'), image: q('.photo-lightbox-image'),
            counter: q('.photo-lightbox-counter'), loading: q('.photo-lightbox-loading'),
            message: q('.photo-lightbox-message'), prev: q('.photo-lightbox-prev'),
            next: q('.photo-lightbox-next'), close: q('.photo-lightbox-close'),
            group: null, index: 0, opener: null, generation: 0,
        };

        self.setLabels = (group) => {
            const text = group.labels;
            dialog.setAttribute('aria-label', text.gallery);
            self.close.setAttribute('aria-label', text.close);
            self.prev.setAttribute('aria-label', text.previous);
            self.next.setAttribute('aria-label', text.next);
            self.loading.querySelector('.visually-hidden').textContent = text.loading;
            self.message.querySelector('p').textContent = text.error;
            self.message.querySelector('button').textContent = text.retry;
            dialog.className = `photo-lightbox ${group.className || ''}`.trim();
        };

        self.show = index => {
            const group = self.group;
            const count = group.links.length;
            self.index = (index + count) % count;
            const link = group.links[self.index];
            const generation = ++self.generation;
            self.figure.querySelectorAll(':scope > :not(.photo-lightbox-image)').forEach(extra => extra.remove());
            self.image.hidden = true;
            self.message.hidden = true;
            // CSS delays the spinner, so quick loads do not flash it.
            self.loading.hidden = false;
            self.counter.textContent = count > 1 ? `${self.index + 1}/${count}` : '';
            self.prev.hidden = self.next.hidden = count < 2;
            const settle = () => { self.loading.hidden = true; };
            self.image.onload = () => {
                if (generation !== self.generation) return;
                settle();
                self.image.hidden = false;
                if (group.onShow) group.onShow(self, link);
            };
            self.image.onerror = () => {
                if (generation !== self.generation) return;
                settle();
                self.message.hidden = false;
                self.message.querySelector('button').focus();
            };
            const thumbnail = link.querySelector('img');
            self.image.alt = thumbnail ? thumbnail.alt : '';
            // Re-setting the attribute also retries a failed address.
            self.image.removeAttribute('src');
            self.image.src = link.href;
        };

        self.open = (group, index, opener) => {
            self.group = group;
            self.opener = opener;
            self.setLabels(group);
            if (!dialog.open) {
                dialog.showModal();
                document.documentElement.classList.add('photo-lightbox-open');
            }
            self.show(index);
            self.close.focus();
        };

        // Runs on every way of closing; repeated calls are harmless.
        const cleanUp = () => {
            // Abandon a pending load; its late load or error event is ignored.
            self.generation += 1;
            self.image.onload = self.image.onerror = null;
            self.image.removeAttribute('src');
            self.image.hidden = true;
            self.loading.hidden = true;
            self.message.hidden = true;
            document.documentElement.classList.remove('photo-lightbox-open');
            const opener = self.opener;
            self.opener = null;
            if (opener && opener.isConnected) opener.focus();
        };
        self.shut = () => {
            if (dialog.open) dialog.close();
            cleanUp();
        };
        // The close event arrives asynchronously; Escape closes right away.
        dialog.addEventListener('cancel', event => {
            event.preventDefault();
            self.shut();
        });
        dialog.addEventListener('close', cleanUp);
        self.close.addEventListener('click', self.shut);
        self.prev.addEventListener('click', () => self.show(self.index - 1));
        self.next.addEventListener('click', () => self.show(self.index + 1));
        self.message.querySelector('button').addEventListener('click', () => self.show(self.index));
        dialog.addEventListener('keydown', event => {
            if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                if (self.group.links.length < 2) return;
                event.preventDefault();
                self.show(self.index + (event.key === 'ArrowRight' ? 1 : -1));
            }
        });

        // Swipe to browse; a plain click on the photo or the backdrop closes.
        let start = null;
        let moved = false;
        const pointers = new Set();
        dialog.addEventListener('pointerdown', event => {
            // A new primary pointer starts a new gesture, even if the end of
            // the previous one was never reported.
            if (event.isPrimary) {
                pointers.clear();
                start = {x: event.clientX, y: event.clientY};
                moved = false;
            } else {
                moved = true;
            }
            pointers.add(event.pointerId);
        });
        dialog.addEventListener('pointermove', event => {
            if (start && pointers.has(event.pointerId) &&
                Math.hypot(event.clientX - start.x, event.clientY - start.y) > 8) {
                moved = true;
            }
        });
        const release = event => {
            if (!pointers.delete(event.pointerId)) return;
            if (event.type === 'pointercancel') moved = true;
            const dx = event.clientX - start.x;
            const dy = event.clientY - start.y;
            if (event.type === 'pointerup' && !pointers.size && Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) &&
                self.group.links.length > 1 && !event.target.closest('.item-image-ocr, button')) {
                self.show(self.index + (dx < 0 ? 1 : -1));
            }
        };
        window.addEventListener('pointerup', release);
        window.addEventListener('pointercancel', release);
        dialog.addEventListener('click', event => {
            if (moved) return;
            if (event.target === self.image || event.target === dialog ||
                event.target.classList.contains('photo-lightbox-stage')) self.shut();
        });
        return self;
    }

    window.setupPhotoLightbox = (links, {className, labels, onShow} = {}) => {
        links = Array.from(links);
        if (!links.length || typeof HTMLDialogElement === 'undefined') return null;
        if (!viewer) viewer = createViewer();
        const group = {links, className, labels, onShow};
        links.forEach((link, index) => {
            link.addEventListener('click', event => {
                if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                viewer.open(group, index, link);
            });
        });
        return {group, get viewer() { return viewer; }};
    };
})();
