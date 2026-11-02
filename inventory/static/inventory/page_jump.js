// Back to the top (base.html): the buttons show whenever the page is not at its very top. Pages add buttons to
// their sections (location_detail.js marks the one being read).
(() => {
    const jump = document.querySelector('[data-page-jump]');
    if (!jump) return;
    const update = () => { jump.hidden = window.scrollY < 1; };
    window.addEventListener('scroll', update, {passive: true});
    update();
    jump.querySelector('[data-page-jump-top]').addEventListener('click', event => {
        event.preventDefault();
        window.scrollTo({top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    });
})();
