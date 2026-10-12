// The label ID field only matters when a pre-printed label is used.
(() => {
    const groups = new Set([...document.querySelectorAll('input[name$="zam_choice"]')].map(input => input.name));
    groups.forEach(name => {
        const code = document.getElementById(`div_id_${name.replace(/zam_choice$/, 'zam_code')}`);
        const choices = document.querySelectorAll(`input[name="${name}"]`);
        if (!code) return;
        const reserved = () => document.querySelector(`input[name="${name}"]:checked`)?.value === 'reserved';
        choices.forEach(choice => choice.addEventListener('change', () => {
            code.hidden = !reserved();
            if (reserved()) code.querySelector('input')?.focus();
        }));
        code.hidden = !reserved();
    });
})();
