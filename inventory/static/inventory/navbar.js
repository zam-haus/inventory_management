// The navbar sticks to the top (sticky-top), slides away while scrolling down and comes back
// as soon as the page is scrolled up a little. It stays at the top of the page, while its menus
// are open and while it has the keyboard focus.
(() => {
    const navbar = document.querySelector('.app-navbar');
    if (!navbar) return;
    const SHOW_AFTER = 10;  // px scrolled up before it comes back
    let lastY = Math.max(0, window.scrollY);
    let scrolledUp = 0;
    let pending = false;

    const show = () => navbar.classList.remove('is-hidden');
    const busy = () => navbar.querySelector('.navbar-collapse.show, .navbar-collapse.collapsing, .dropdown-menu.show')
        || navbar.contains(document.activeElement);

    function update() {
        pending = false;
        const y = Math.max(0, window.scrollY);  // iOS bounces below 0 at the top
        const delta = y - lastY;
        lastY = y;
        if (y <= navbar.offsetHeight || busy()) {
            scrolledUp = 0;
            show();
        } else if (delta > 0) {
            scrolledUp = 0;
            navbar.classList.add('is-hidden');
        } else if (delta < 0) {
            scrolledUp -= delta;
            if (scrolledUp >= SHOW_AFTER) show();
        }
    }

    window.addEventListener('scroll', () => {
        if (pending) return;
        pending = true;
        window.requestAnimationFrame(update);
    }, {passive: true});
    navbar.addEventListener('focusin', show);
})();
