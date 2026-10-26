// The item and location trees (item_tree.html, location_tree.html, docs/trees.md): every node opens and
// closes without JavaScript (<details>). This adds "Open all" and "Close all", opens the way to a node named in
// the address (#loc-123, #cat-45), marking it, and the keyboard: the first arrow key starts at the first row
// (or at the row under the mouse, which has the focus); up and down move through the visible rows,
// right opens a branch, left closes it (or the one it is in), space opens or closes it, and Enter opens the
// page of the location or category itself.
(() => {
    const tree = document.querySelector('[data-tree]');
    if (!tree) return;

    function setAll(open) {
        tree.querySelectorAll('details').forEach(details => { details.open = open; });
    }
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
        node.scrollIntoView({block: 'center'});
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
    const rows = () => [...tree.querySelectorAll('summary, li.tree-leaf > .tree-row a')].filter(visible);
    const rowOf = element => element?.closest?.('summary')
        || element?.closest?.('li.tree-leaf')?.querySelector(':scope > .tree-row a') || null;
    const linkOf = row => (row.matches('a') ? row : row.querySelector('a'));
    let marked = null;

    function mark(row) {
        marked?.classList.remove('is-current');
        marked = row && (row.matches('summary') ? row : row.closest('li.tree-leaf'));
        marked?.classList.add('is-current');
    }
    tree.addEventListener('focusin', event => mark(rowOf(event.target)));
    tree.addEventListener('focusout', event => {
        if (!tree.contains(event.relatedTarget)) mark(null);
    });
    tree.addEventListener('mouseover', event => {
        const row = rowOf(event.target);
        if (row && !row.contains(document.activeElement) && visible(row)) row.focus({preventScroll: true});
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
