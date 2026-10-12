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
