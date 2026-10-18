// Installed app: there is no pull-to-refresh of the browser. Pulling down at the top far enough
// reloads the page; an indicator follows the finger (pull_refresh.css). Browser tabs keep their
// own pull-to-refresh.
(() => {
    const installed = window.matchMedia('(display-mode: standalone), (display-mode: fullscreen)').matches
        || navigator.standalone === true;
    if (!installed || !('ontouchstart' in window)) return;
    const THRESHOLD = 80;
    const indicator = document.createElement('div');
    indicator.className = 'pull-refresh';
    indicator.setAttribute('aria-hidden', 'true');
    document.body.append(indicator);
    let startY = null;
    let distance = 0;

    function reset() {
        startY = null;
        distance = 0;
        indicator.style.removeProperty('--pull');
        indicator.style.removeProperty('--pull-turn');
        indicator.classList.remove('is-pulling', 'is-ready');
    }

    window.addEventListener('touchstart', event => {
        // Not while a dialog is open or a menu scrolls.
        const busy = document.querySelector('.modal.show, dialog[open], .dropdown-menu.show');
        startY = window.scrollY <= 0 && event.touches.length === 1 && !busy ? event.touches[0].clientY : null;
        distance = 0;
    }, {passive: true});
    window.addEventListener('touchmove', event => {
        if (startY === null) return;
        if (window.scrollY > 0) {
            reset();
            return;
        }
        distance = Math.max(0, event.touches[0].clientY - startY);
        // Resistance: the indicator moves slower than the finger, and turns as it comes.
        const pulled = Math.min(distance, THRESHOLD * 1.5) * 0.6;
        indicator.style.setProperty('--pull', `${pulled}px`);
        indicator.style.setProperty('--pull-turn', `${pulled * 3}deg`);
        indicator.classList.toggle('is-pulling', distance > 0);
        indicator.classList.toggle('is-ready', distance >= THRESHOLD);
    }, {passive: true});
    window.addEventListener('touchend', () => {
        if (startY !== null && distance >= THRESHOLD) {
            indicator.classList.add('is-reloading');
            window.location.reload();
            return;
        }
        reset();
    });
    window.addEventListener('touchcancel', reset);
})();
