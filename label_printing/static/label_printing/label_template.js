// A label template's admin page (label_printing/editor.py): the description with its preview beside it, which
// the server renders while it is typed, the problems by line, and the fields of the chosen kind of label.
// In the description Tab indents by two spaces, Shift+Tab outdents, Enter keeps the indentation.
(() => {
    const data = JSON.parse(document.getElementById('label-editor-data').textContent);
    const description = document.getElementById('id_description');
    const kind = document.getElementById('id_subject_type');
    if (!description) return;

    const showFields = () => document.querySelectorAll('[data-label-fields]').forEach(table => {
        table.hidden = Boolean(kind) && table.dataset.labelFields !== kind.value;
    });
    showFields();

    // The preview beside the description
    const panel = document.getElementById('label-preview-template').content.firstElementChild.cloneNode(true);
    const row = document.createElement('div');
    row.className = 'label-description-row';
    description.replaceWith(row);
    row.append(description, panel);
    const part = name => panel.querySelector(`[data-preview-${name}]`);
    for (const medium of data.media) part('medium').add(new Option(medium.name, medium.id));

    let timer = null;
    let sequence = 0;
    async function refresh() {
        const current = ++sequence;
        const body = new FormData();
        body.append('description', description.value);
        body.append('subject_type', kind ? kind.value : 'location');
        body.append('record', part('record').value || '0');
        body.append('medium', part('medium').value);
        let result;
        try {
            const response = await fetch(data.preview_url, {
                method: 'POST', body, credentials: 'same-origin',
                headers: {'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value},
            });
            result = await response.json();
        } catch {
            return;  // the last preview stays
        }
        if (current !== sequence) return;
        const image = part('image');
        image.hidden = !result.image;
        if (result.image) image.src = result.image;
        part('size').textContent = result.size || '';
        const records = part('record');
        const chosen = records.value;
        if (records.options.length !== result.records.length
                || [...records.options].some((option, index) => option.text !== result.records[index])) {
            records.replaceChildren(...result.records.map((name, index) => new Option(name, index)));
            if (chosen && Number(chosen) < result.records.length) records.value = chosen;
        }
        part('problems').replaceChildren(...result.problems.map(problem => {
            const item = document.createElement('li');
            const link = document.createElement('a');
            link.textContent = `${problem.line}:`;
            link.addEventListener('click', () => selectLine(problem.line));
            item.append(link, ' ', problem.message);
            return item;
        }));
    }
    const schedule = () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(refresh, 250);
    };

    function selectLine(number) {
        const lines = description.value.split('\n');
        const start = lines.slice(0, number - 1).reduce((sum, line) => sum + line.length + 1, 0);
        description.focus();
        description.setSelectionRange(start, start + (lines[number - 1] || '').length);
    }

    // Editing an indented language
    description.addEventListener('keydown', event => {
        const {selectionStart: start, selectionEnd: end, value} = description;
        const lineStart = value.lastIndexOf('\n', start - 1) + 1;
        if (event.key === 'Tab') {
            event.preventDefault();
            const lineEnd = value.indexOf('\n', end) === -1 ? value.length : value.indexOf('\n', end);
            const block = value.slice(lineStart, lineEnd);
            const changed = event.shiftKey ? block.replace(/^ {1,2}/gm, '') : block.replace(/^/gm, '  ');
            description.setRangeText(changed, lineStart, lineEnd, 'preserve');
            if (start === end && !event.shiftKey) description.setSelectionRange(start + 2, start + 2);
            schedule();
        } else if (event.key === 'Enter' && start === end) {
            event.preventDefault();
            const indent = value.slice(lineStart, start).match(/^ */)[0];
            description.setRangeText(`\n${indent}`, start, end, 'end');
            schedule();
        }
    });
    description.addEventListener('input', schedule);
    kind?.addEventListener('change', () => { showFields(); part('record').value = ''; schedule(); });
    part('record').addEventListener('change', schedule);
    part('medium').addEventListener('change', schedule);
    refresh();
})();
