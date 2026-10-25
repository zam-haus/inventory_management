// The admin's list of label templates (inventory/admin.py, LocationLabelTemplateAdmin.sample): each template's
// label with a few random records of its kind. While the pointer is on it, it shows one record after another.
// Loaded in the page's head (ModelAdmin.Media), so it waits for the list.
document.addEventListener('DOMContentLoaded', () => {
    const STEP_MS = 1200;
    for (const image of document.querySelectorAll('img[data-label-samples]')) {
        const samples = JSON.parse(image.dataset.labelSamples);  // [[url, record], …]
        if (samples.length < 2) continue;
        let index = 0;
        let timer = null;
        const show = next => {
            index = next % samples.length;
            [image.src, image.title] = samples[index];
        };
        image.addEventListener('mouseenter', () => {
            for (const [url] of samples) new Image().src = url;  // fetched once, from then on cached
            show(index + 1);
            timer = setInterval(() => show(index + 1), STEP_MS);
        });
        image.addEventListener('mouseleave', () => clearInterval(timer));
    }
});
