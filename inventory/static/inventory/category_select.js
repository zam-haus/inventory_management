// Category fields (widgets.CategorySelect). With jQuery and Select2 on the page the field becomes a search:
// every word typed must occur in the category's path, its keywords or in what belongs there (the
// description's first line, not its "Nicht hier" hints); hits on the name come first, then on the path and
// keywords; an entry found by a keyword names it. Without a search the list shows the tree,
// indented, each entry with the first line of its description. The chosen category's description
// shows below the field; a category filter (data-category-filter) applies on choosing. Listens on the
// document, so that fields in forms loaded later and forms being reset are covered too.
(() => {
    const show = select => {
        const description = select.parentElement.querySelector('[data-category-description]');
        if (description) description.textContent = select.selectedOptions[0]?.dataset.description || '';
    };
    const chosen = select => {
        if (select.matches('[data-category-filter]')) select.form?.requestSubmit();
        else show(select);
    };

    const words = term => term.toLocaleLowerCase().split(/\s+/).filter(Boolean);
    const summary = option => (option.dataset.description || '').split('\n')[0];
    const keywords = option => (option.dataset.keywords || '').split(',').map(word => word.trim()).filter(Boolean);
    const fits = (option, terms) => {
        const text = `${option.dataset.path} ${option.dataset.keywords || ''} ${summary(option)}`.toLocaleLowerCase();
        return terms.every(word => text.includes(word));
    };
    // 0: every word in the name, 1: in the path or keywords, 2: also in the description.
    const rank = (option, terms) => {
        const name = option.dataset.name.toLocaleLowerCase();
        const near = `${option.dataset.path} ${option.dataset.keywords || ''}`.toLocaleLowerCase();
        return terms.every(word => name.includes(word)) ? 0 : terms.every(word => near.includes(word)) ? 1 : 2;
    };
    // The keywords containing a word typed that neither the path nor the description shows.
    const foundBy = (option, terms) => {
        const shown = `${option.dataset.path} ${summary(option)}`.toLocaleLowerCase();
        const missing = terms.filter(word => !shown.includes(word));
        return keywords(option).filter(keyword => missing.some(word => keyword.toLocaleLowerCase().includes(word)));
    };
    const matcher = (params, data) => {
        const terms = words(params.term || '');
        if (!terms.length) return data;
        if (data.children) {
            const children = data.children.filter(child => child.element?.dataset.path && fits(child.element, terms));
            return children.length ? {...data, children} : null;
        }
        return data.element?.dataset.path && fits(data.element, terms) ? data : null;
    };

    const element = (tag, className, text) => {
        const node = document.createElement(tag);
        node.className = className;
        node.textContent = text;
        return node;
    };
    const result = (data, terms) => {
        const searching = terms.length > 0;
        const option = data.element;
        if (!option?.dataset?.path) return data.text;  // group labels, the empty choice, messages
        const entry = element('div', 'category-option', '');
        entry.style.setProperty('--depth', searching ? 0 : option.dataset.depth);
        entry.append(element('div', 'category-option-name', option.dataset.name));
        const above = option.dataset.path.split(' › ').slice(0, -1).join(' › ');
        if (searching && above) entry.append(element('div', 'category-option-path', above));
        const matched = searching ? foundBy(option, terms) : [];
        if (matched.length) entry.append(element('div', 'category-option-keywords', matched.join(', ')));
        if (summary(option)) entry.append(element('div', 'category-option-description', summary(option)));
        return entry;
    };

    const enhance = select => {
        const $ = window.jQuery;
        if (!$?.fn?.select2 || select.dataset.select2Id) return;
        const $select = $(select);
        let terms = [];
        $select.select2({
            width: '100%',
            containerCssClass: ':all:',  // the box looks like the Bootstrap .form-select (autocomplete.css)
            allowClear: !select.required,
            placeholder: select.dataset.placeholder || '',
            language: document.documentElement.lang || 'en',
            matcher: (params, data) => {
                terms = words(params.term || '');
                return matcher(params, data);
            },
            // While searching, one list without the top category headings (each hit shows its path), best first.
            sorter: data => {
                if (!terms.length) return data;
                const hits = data.flatMap(entry => entry.children || [entry]).filter(entry => entry.element?.dataset?.path);
                return hits.map((entry, index) => [rank(entry.element, terms), index, entry])
                    .sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([, , entry]) => entry);
            },
            templateResult: data => result(data, terms),
            templateSelection: data => data.element?.dataset?.path || data.text,
            dropdownCssClass: 'category-dropdown',
        });
        // Select2 announces the choice as a jQuery event only.
        $select.on('select2:select select2:clear', () => chosen(select));
        // The search box gets the focus when the list opens.
        $select.on('select2:open', () => document.querySelector('.select2-container--open .select2-search__field')?.focus());
    };

    const enhanceAll = root => root.querySelectorAll('select[data-category-select]').forEach(enhance);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => enhanceAll(document));
    else enhanceAll(document);

    document.addEventListener('change', event => {
        if (event.target.matches('select[data-category-select]') && !event.target.dataset.select2Id) chosen(event.target);
    });
    document.addEventListener('reset', event => {
        setTimeout(() => event.target.querySelectorAll('select[data-category-select]').forEach(select => {
            window.jQuery?.(select).trigger('change.select2');
            show(select);
        }));
    });
})();
