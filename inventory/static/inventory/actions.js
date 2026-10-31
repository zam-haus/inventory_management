// Icons for scripts (templates/script_templates.html): window.appIcon('star-fill') returns an inline SVG.
window.appIcon = name => {
    const template = document.querySelector(`#app-icons template[data-icon="${name}"]`);
    return template ? template.content.cloneNode(true) : document.createDocumentFragment();
};

// Bootstrap tooltips for every [data-bs-toggle="tooltip"] on the page, and the
// helpers for buttons that stay visible while unavailable (.disabled-action).
(() => {
    const tooltips = [];

    function attachTooltip(element) {
        if (typeof bootstrap === 'undefined' || !bootstrap.Tooltip) return null;
        const tooltip = new bootstrap.Tooltip(element, {container: 'body', trigger: 'hover focus'});
        tooltips.push(tooltip);
        // Help controls and disabled actions also explain themselves when tapped, for touch screens.
        if (element.matches('.location-help, .item-help, .disabled-action')) {
            element.addEventListener('click', () => {
                element.focus();
                tooltip.show();
            });
        }
        return tooltip;
    }

    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(attachTooltip);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') tooltips.forEach(tooltip => tooltip.hide());
    });

    // Buttons that need JavaScript are rendered disabled inside a .disabled-action
    // wrapper that explains why. Scripts then enable them, or explain another reason.
    window.inventoryActions = {
        enable(button) {
            const wrapper = button.closest('.disabled-action');
            button.disabled = false;
            if (!wrapper) return;
            window.bootstrap?.Tooltip.getInstance(wrapper)?.dispose();
            wrapper.replaceWith(button);
        },
        explain(button, reason) {
            const wrapper = button.closest('.disabled-action');
            if (!wrapper) return;
            const tooltip = window.bootstrap?.Tooltip.getInstance(wrapper);
            if (tooltip) {
                tooltip.setContent({'.tooltip-inner': reason});
                return;
            }
            // Wrappers added by scripts after the page loaded get their tooltip here.
            wrapper.title = reason;
            attachTooltip(wrapper);
        },
    };
})();

// Action rows: a title and its actions ([data-action-row] containing [data-action-group]). When the actions do not
// fit beside the title, a menu at the right end (#action-menu-template) takes them in this order, until the rest
// fits: first the unavailable ones (.disabled-action), one by one from the right; then the usable ones show their
// icon only (all at once, so the row stays alike) and are listed in the menu, too; last the usable ones move into
// it, from the right. Important actions ([data-action-primary], e.g. taking stock out) stay while usable. With none
// left, the menu alone stays beside the title. Menu entries forward clicks to the hidden originals, which keep their
// behaviour; unavailable actions are listed disabled with their reason.
(() => {
    const template = document.getElementById('action-menu-template');
    if (!template || !window.bootstrap?.Dropdown || typeof ResizeObserver === 'undefined') return;

    function entry(action) {
        const unavailable = action.matches('.disabled-action');
        const item = document.createElement(unavailable ? 'div' : action.matches('a[href]') ? 'a' : 'button');
        item.className = 'dropdown-item action-menu-item';
        // Entries without an icon keep its column, so the labels line up.
        const icon = action.querySelector('svg.bi');
        item.append(icon ? icon.cloneNode(true) : document.createElement('span'));
        const label = document.createElement('span');
        label.textContent = action.getAttribute('aria-label') || action.textContent.trim();
        item.append(label);
        if (unavailable) {
            item.classList.add('disabled');
            item.setAttribute('aria-disabled', 'true');
            const reason = document.getElementById(action.getAttribute('aria-describedby'))?.textContent;
            if (reason) {
                const text = document.createElement('small');
                text.className = 'action-menu-reason';
                text.textContent = reason;
                item.append(text);
            }
        } else {
            if (item.tagName === 'A') item.href = action.href;
            else item.type = 'button';
            if (action.matches('.btn-danger')) item.classList.add('text-danger');
            item.addEventListener('click', event => {
                event.preventDefault();
                action.click();
            });
        }
        const li = document.createElement('li');
        li.append(item);
        return li;
    }

    const overflowed = action => action.classList.contains('is-overflowed');
    const primary = action => action.hasAttribute('data-action-primary');
    const compact = action => action.classList.contains('is-compact');
    const unavailable = action => action.matches('.disabled-action');

    // Its icon only; its text, now hidden, stays its name and tooltip.
    function shorten(action) {
        action.classList.add('is-compact');
        const name = action.textContent.trim();
        if (!action.hasAttribute('aria-label')) {
            action.setAttribute('aria-label', name);
            action.dataset.compactName = 'true';
        }
        if (!action.hasAttribute('title') && !action.hasAttribute('data-bs-original-title')) {
            action.setAttribute('title', name);
            action.dataset.compactTitle = 'true';
        }
    }
    const rows = [...document.querySelectorAll('[data-action-row]')].map(row => {
        const group = row.querySelector('[data-action-group]');
        if (!group || group === row.firstElementChild) return null;
        const menu = template.content.firstElementChild.cloneNode(true);
        const toggle = menu.querySelector('[data-bs-toggle="dropdown"]');
        const list = menu.querySelector('.dropdown-menu');
        menu.hidden = true;
        group.after(menu);
        const actions = () => [...group.children].filter(action => !action.hidden);
        // Built when opened, so it shows the actions as they are now (scripts enable some).
        menu.addEventListener('show.bs.dropdown', () => {
            list.replaceChildren(...actions().filter(action => group.hidden || overflowed(action) || compact(action))
                .map(entry));
        });
        const fit = () => {
            const all = actions();
            row.classList.remove('is-collapsed');
            group.hidden = false;
            menu.hidden = true;
            all.forEach(action => {
                action.classList.remove('is-overflowed', 'is-compact');
                // The name and tooltip given while it showed its icon only.
                if (action.dataset.compactName) action.removeAttribute('aria-label');
                if (action.dataset.compactTitle) action.removeAttribute('title');
                delete action.dataset.compactName;
                delete action.dataset.compactTitle;
            });
            // Below the title, or on more than one line beside it.
            const wraps = () => {
                const shown = all.filter(action => !overflowed(action));
                const top = shown.length ? shown[0].getBoundingClientRect().top : 0;
                return [...shown, menu].some(element => !element.hidden
                    && (element.getBoundingClientRect().top >= row.firstElementChild.getBoundingClientRect().bottom - 1
                        || (element !== menu && element.getBoundingClientRect().top > top + 1)));
            };
            // Guests may see no actions at all.
            if (!all.length || !wraps()) {
                bootstrap.Dropdown.getInstance(toggle)?.hide();
                return;
            }
            menu.hidden = false;
            const usable = all.filter(action => !unavailable(action));
            const fromRight = list => [...list].reverse();
            const steps = [
                ...fromRight(all.filter(unavailable)).map(action => () => action.classList.add('is-overflowed')),
                () => usable.filter(action => action.querySelector('.action-label')).forEach(shorten),
                ...fromRight(usable.filter(action => !primary(action)))
                    .map(action => () => action.classList.add('is-overflowed')),
            ];
            for (const step of steps) {
                if (!wraps()) break;
                step();
            }
            if (all.every(overflowed)) {  // only the menu, beside the title, which wraps instead
                row.classList.add('is-collapsed');
                group.hidden = true;
            } else if (wraps()) {  // the important ones and the menu beside the title, which wraps instead
                row.classList.add('is-collapsed');
            }
        };
        let width = 0;
        new ResizeObserver(([change]) => {
            const newWidth = Math.round(change.contentRect.width);
            if (newWidth === width) return;
            width = newWidth;
            fit();
        }).observe(row);
        return fit;
    }).filter(Boolean);

    // Web fonts change the title's width without resizing the row.
    document.fonts?.ready.then(() => rows.forEach(fit => fit()));
})();
