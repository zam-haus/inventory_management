// New items: bulk or tracked as unique items. Both parts are on the page;
// switching shows the chosen one and keeps everything entered.
(() => {
    const choices = [...document.querySelectorAll('input[name="kind"][data-kind-switch]')];
    if (!choices.length) return;
    const update = () => {
        const kind = choices.find(choice => choice.checked)?.value || 'bulk';
        document.querySelectorAll('[data-for-kind]').forEach(element => {
            element.hidden = element.dataset.forKind !== kind;
        });
    };
    choices.forEach(choice => choice.addEventListener('change', update));
    update();
})();
