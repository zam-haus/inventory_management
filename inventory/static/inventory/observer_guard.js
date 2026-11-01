// django-autocomplete-light watches the whole page from the moment it loads (a MutationObserver on <html>) and runs
// jQuery's find() on every node added anywhere, which sets and removes a temporary id on it. Inside the Markdown
// editor (ProseMirror, markdown_editor.js) those attribute changes count as edits: the editor draws anew, adds
// nodes, dal looks at them again, and Firefox hangs in that loop while typing. So observers of the whole page get
// no records from inside [data-observer-private] (the editor); observers of anything smaller, such as the editor's
// own, get all of theirs. Loaded before dal's script (widgets.AutocompleteSelect).
(() => {
    const Native = window.MutationObserver;
    if (!Native || Native.guardsPrivateParts) return;
    const wholePage = target => target === document || target === document.documentElement || target === document.body;
    const isPrivate = node => Boolean((node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement)
        ?.closest('[data-observer-private]'));

    class GuardedMutationObserver extends Native {
        constructor(callback) {
            super((records, observer) => {
                const kept = this.watchesWholePage ? records.filter(record => !isPrivate(record.target)) : records;
                if (kept.length) callback.call(observer, kept, observer);
            });
            this.watchesWholePage = false;
        }

        observe(target, options) {
            if (wholePage(target)) this.watchesWholePage = true;
            return super.observe(target, options);
        }
    }
    GuardedMutationObserver.guardsPrivateParts = true;
    window.MutationObserver = GuardedMutationObserver;
})();
