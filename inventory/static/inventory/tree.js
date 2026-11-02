// The item and location trees (item_tree.html, location_tree.html, docs/trees.md): every node opens and
// closes without JavaScript (<details>). This adds "Open all" and "Close all", opens the way to a node named in
// the address (#loc-123, #cat-45), marking it, and the keyboard: the first arrow key starts at the first row
// (or at the row under the mouse, which has the focus); up and down move through the visible rows,
// right opens a branch, left closes it (or the one it is in), space opens or closes it, and Enter opens the
// page of the location or category itself. In the item tree, an open category loads the items right in it as
// result rows (/item/rows/, more while scrolling: results.js) once they come into view: at once when opened by
// hand, after "Open all" while scrolling down; a link loads them, too. The arrow keys go from a category into its
// rows and on from the first or last of them back into the tree (results:leave); within them results.js moves.
(() => {
    const tree = document.querySelector('[data-tree]');
    if (!tree) return;

    function setAll(open) {
        tree.querySelectorAll('details').forEach(details => { details.open = open; });
    }

    async function loadItems(holder) {
        if (holder.dataset.loaded) return;
        holder.dataset.loaded = 'true';
        const link = holder.querySelector('[data-tree-items-load]');
        link?.setAttribute('aria-busy', 'true');
        try {
            const response = await fetch(holder.dataset.treeItems, {credentials: 'same-origin', headers: {Accept: 'text/html'}});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            holder.innerHTML = await response.text();
            window.inventoryResults?.watch(holder);
        } catch (failure) {
            delete holder.dataset.loaded;  // the link stays, to try again
            link?.removeAttribute('aria-busy');
        }
    }
    const coming = 'IntersectionObserver' in window ? new IntersectionObserver(entries => entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        coming.unobserve(entry.target);
        loadItems(entry.target);
    }), {rootMargin: '300px 0px'}) : null;
    tree.addEventListener('toggle', event => {
        const holder = event.target.open && event.target.querySelector(':scope > ul > li[data-tree-items]:not([data-loaded])');
        if (!holder) return;
        if (coming) coming.observe(holder);
        else loadItems(holder);
    }, true);  // toggle does not bubble
    tree.addEventListener('click', event => {
        const link = event.target.closest('[data-tree-items-load]');
        if (!link) return;
        event.preventDefault();
        loadItems(link.closest('[data-tree-items]'));
    });
    document.querySelectorAll('[data-tree-open]').forEach(button => {
        button.hidden = false;
        button.addEventListener('click', () => setAll(true));
    });
    document.querySelectorAll('[data-tree-close]').forEach(button => {
        button.hidden = false;
        button.addEventListener('click', () => setAll(false));
    });

    function reveal() {
        const id = decodeURIComponent(window.location.hash.slice(1));
        const node = id && document.getElementById(id);
        if (!node || !tree.contains(node)) return;
        for (let details = node.parentElement.closest('details'); details; details = details.parentElement.closest('details')) {
            details.open = true;
        }
        node.querySelector(':scope > details')?.setAttribute('open', '');
        tree.querySelectorAll('[aria-current]').forEach(marked => marked.removeAttribute('aria-current'));
        node.setAttribute('aria-current', 'true');
        // In the middle of the view; an open branch taller than it from its start, below what stays at the top.
        node.scrollIntoView({block: node.getBoundingClientRect().height > window.innerHeight / 2 ? 'start' : 'center'});
    }
    reveal();
    window.addEventListener('hashchange', reveal);

    // Keyboard and mouse. A row is a branch's <summary> or a leaf's link. Rows in a closed branch are hidden:
    // told by the branches above it, as Chrome keeps layout boxes for them (content-visibility), so that
    // getClientRects() would count them. The pointer over a row moves the focus there; the focused row is
    // marked (is-current), so mouse and keyboard show the same row and go on from it.
    const visible = row => {
        const start = (row.matches('summary') ? row.parentElement : row).parentElement;
        for (let details = start.closest('details'); details; details = details.parentElement.closest('details')) {
            if (!details.open) return false;
        }
        return true;
    };
    // Also the result rows of a category's items: the arrow keys come into them from the tree (results.js then).
    const rows = () => [...tree.querySelectorAll('summary, li.tree-leaf > .tree-row a, li[data-result-entry] .result-link')]
        .filter(visible);
    const rowOf = element => element?.closest?.('summary')
        || element?.closest?.('li.tree-leaf')?.querySelector(':scope > .tree-row a') || null;
    const linkOf = row => (row.matches('a') ? row : row.querySelector('a'));
    let marked = null;

    function mark(row) {
        marked?.classList.remove('is-current');
        marked = row && (row.matches('summary') ? row : row.closest('li.tree-leaf'));
        marked?.classList.add('is-current');
        // One row marked at a time: a result row results.js marked is no longer the current one.
        if (marked) tree.querySelectorAll('.result-entry.is-marked').forEach(entry => entry.classList.remove('is-marked'));
    }
    tree.addEventListener('focusin', event => mark(rowOf(event.target)));
    tree.addEventListener('focusout', event => {
        if (!tree.contains(event.relatedTarget)) mark(null);
    });
    tree.addEventListener('mouseover', event => {
        const row = rowOf(event.target);  // result rows: results.js
        if (row && !row.contains(document.activeElement) && visible(row)) row.focus({preventScroll: true});
    });

    // Off the first or the last of a category's rows: on to the row of the tree above or below them.
    tree.addEventListener('results:leave', event => {
        const list = rows();
        const next = list[list.indexOf(event.target.querySelector('.result-link')) + event.detail.direction];
        if (!next) return;
        event.preventDefault();
        next.focus();
        next.scrollIntoView({block: 'nearest'});
    });

    function focus(row, event) {
        if (!row) return;
        event.preventDefault();
        row.focus();
        row.scrollIntoView({block: 'nearest'});
    }

    document.addEventListener('keydown', event => {
        if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        const row = tree.contains(document.activeElement) ? rowOf(document.activeElement) : null;
        if (!row) {
            // Not in the tree yet: the arrow keys start there (not from fields or buttons elsewhere).
            const elsewhere = document.activeElement && document.activeElement !== document.body;
            if (!elsewhere && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) focus(rows()[0], event);
            return;
        }
        const details = row.matches('summary') ? row.parentElement : null;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            const list = rows();
            focus(list[list.indexOf(row) + (event.key === 'ArrowDown' ? 1 : -1)], event);
        } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            if (details) details.open = true;
        } else if (event.key === 'ArrowLeft') {
            // Close this branch; on a closed branch or a leaf, close the one it is in and go there.
            event.preventDefault();
            if (details?.open) {
                details.open = false;
            } else {
                const parent = (details || row).parentElement.closest('details');
                if (!parent) return;
                parent.open = false;
                focus(parent.querySelector(':scope > summary'), event);
            }
        } else if (event.key === ' ' && details) {
            event.preventDefault();
            details.open = !details.open;
        } else if (event.key === 'Enter') {
            event.preventDefault();
            window.location.assign(linkOf(row).href);
        }
    });
})();

// The breadcrumbs follow the tree (item_tree.html, location_tree.html): while scrolling, the path to the deepest
// open node at the top of the view, below the breadcrumbs, each crumb with its icon and leading to its node; the
// last one is where the view is. Each level is searched by halves, as a level may have hundreds of nodes.
(() => {
    const tree = document.querySelector('[data-tree]');
    const crumbs = document.querySelector('[data-tree-breadcrumb]');
    if (!tree || !crumbs) return;
    const root = crumbs.querySelector('a');
    const nodesOf = list => [...list.children].filter(li => li.id && li.querySelector(':scope > details'));

    function at(nodes, line) {  // the node whose box spans the line, if any
        let low = 0, high = nodes.length - 1;
        while (low <= high) {
            const middle = (low + high) >> 1;
            const box = nodes[middle].getBoundingClientRect();
            if (box.bottom <= line) low = middle + 1;
            else if (box.top > line) high = middle - 1;
            else return nodes[middle];
        }
        return null;
    }

    function path() {
        const line = crumbs.closest('[data-page-breadcrumbs]').getBoundingClientRect().bottom + 1;
        const found = [];
        let nodes = nodesOf(tree);
        for (let node = at(nodes, line); node; node = at(nodes, line)) {
            const details = node.querySelector(':scope > details');
            if (!details.open) break;
            found.push(node);
            const list = details.querySelector(':scope > ul');
            if (!list) break;
            nodes = nodesOf(list);
        }
        return found;
    }

    function crumb(node) {
        const summary = node.querySelector(':scope > details > summary');
        const link = document.createElement('a');
        link.href = `#${node.id}`;
        const icon = summary.querySelector('.tree-icon');
        if (icon) link.append(icon.cloneNode(true), ' ');
        const name = summary.querySelector('.loc-title, .tree-name');
        const code = summary.querySelector('.loc-code');
        link.append(name ? name.textContent.trim() : '');
        if (code) {
            const chip = document.createElement('span');
            chip.className = 'loc-code';
            chip.textContent = code.textContent.trim();
            link.append(' ', chip);
        }
        return link;
    }

    let shown = '';
    let pending = false;
    function update() {
        pending = false;
        const nodes = path();
        const key = nodes.map(node => node.id).join(' ');
        if (key === shown) return;
        shown = key;
        crumbs.replaceChildren(root);
        nodes.forEach(node => {
            const separator = document.createElement('span');
            separator.setAttribute('aria-hidden', 'true');
            separator.textContent = '/';
            crumbs.append(' ', separator, ' ', crumb(node));
        });
        crumbs.querySelectorAll('[aria-current]').forEach(link => link.removeAttribute('aria-current'));
        crumbs.lastElementChild.setAttribute('aria-current', nodes.length ? 'location' : 'page');
        crumbs.scrollLeft = crumbs.scrollWidth;
    }
    const schedule = () => { if (!pending) { pending = true; requestAnimationFrame(update); } };
    window.addEventListener('scroll', schedule, {passive: true});
    tree.addEventListener('toggle', schedule, true);
    schedule();
})();
