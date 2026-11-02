# Airtable Interface Forms (`airtable.com/app.../pag.../form`)

Lazy-load this file when filling an Airtable Interface Form.

## Field types in the DOM

An Airtable Interface Form uses three distinct control structures inside
`[data-testid="page-element:formContainer"]`:

1. **Short text fields (`<textarea>` or `<input type="text">`):**
   - Plain short-text questions render as single-line `<textarea id="<hex32>">`
     elements, while numeric, currency, and date (`yyyy-mm-dd`) fields render as
     `<input id="<hex32>" type="text">`.
   - **Hex IDs regenerate on every page reload** (like Ashby). Select them by
     position (`document.querySelectorAll('textarea')[idx]` and
     `[...document.querySelectorAll('input')].filter(i => !i.classList.contains('editableFix'))[idx]`)
     rather than hardcoding the 32-char hex ID.
   - Set via the native `HTMLTextAreaElement.prototype` or
     `HTMLInputElement.prototype` value descriptor, then dispatch bubbling
     `input` and `change` events and `blur()`.

2. **Rich-text long-answer fields (`div[role="textbox"]`):**
   - Long-text fields render as `[role="textbox"]` containers holding an inner
     `[contenteditable="true"]` div (plus a hidden `input.editableFix` decoy).
   - Setting `innerText` or `textContent` directly does **not** clear
     `showPlaceholder` or update Airtable's internal editor state.
   - Working fill pattern (validated 23/10/2026):
     ```js
     const box = document.querySelectorAll('[role=textbox]')[idx];
     const ql = box.querySelector('[contenteditable=true]') || box;
     ql.focus();
     document.execCommand('selectAll', false, null);
     document.execCommand('insertText', false, text);
     ql.dispatchEvent(new Event('input', { bubbles: true }));
     ql.blur();
     ```
   - Verify that `box.classList.contains('showPlaceholder')` is `false` and
     `box.innerText.trim().length > 0`.

3. **Radio groups (`ul[role="radiogroup"]` / `li[role="radio"]`):**
   - Options are `<li id="<hex32>-<index>" role="radio" aria-checked="false">`.
   - Click the `<li>` element and verify `li.getAttribute('aria-checked') === 'true'`.
