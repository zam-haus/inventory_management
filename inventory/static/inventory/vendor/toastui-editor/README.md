# TOAST UI Editor (vendored)

The WYSIWYG Markdown editor of Markdown fields (`inventory/widgets.py`, `MarkdownEditor`;
`inventory/static/inventory/markdown_editor.js`), served locally so pages need no third party.

| File | Source | Version |
|---|---|---|
| `toastui-editor-all.min.js` | `https://uicdn.toast.com/editor/3.2.2/toastui-editor-all.min.js` (the npm package `@toast-ui/editor` only has a build that needs ProseMirror as separate modules) | 3.2.2 |
| `toastui-editor.min.css` | `https://uicdn.toast.com/editor/3.2.2/toastui-editor.min.css` | 3.2.2 |
| `toastui-editor-de-de.min.js` | `https://uicdn.toast.com/editor/3.2.2/i18n/de-de.min.js` | 3.2.2 |

SHA-256 of the files as downloaded:

```
f50e1b7c0fc4e5d9a1ccd0d8be78cb3a950ccb3bf676fbf1627810c76aeaedd8  toastui-editor-all.min.js
c70e24c68fefc205e8e504edc07fd6a5efd3044a623b4be7e3ac16cc8a736ed9  toastui-editor.min.css
289d8890eef834f20fbbfe7c470026b9faf8457eeaaae92e2f0f1e422157b6f7  toastui-editor-de-de.min.js
```

The editor sends usage statistics to Google Analytics unless `usageStatistics: false` is given;
`markdown_editor.js` always gives it.

License: MIT (`LICENSE`, from https://github.com/nhn/tui.editor at tag `editor@3.2.2`).
