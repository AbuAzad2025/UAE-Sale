# JS I18N Agent — STRICT RULES

Work in `D:\recovers\data\UAE-Sale`.

## GOAL
Replace hardcoded Arabic **user-facing UI strings** in your assigned `static/js/*.js` files with the existing JS helper `t('English key')`, so the language switch translates them. `t()` is defined in `static/js/i18n.js` and exposed as `window.t`.

## FILE OWNERSHIP
- Edit ONLY your assigned JS files.
- Write your new keys ONLY to `utils/js_i18n_agent_N.json` (N given to you) as:
  ```json
  {"Print all rows": {"ar": "طباعة جميع الصفوف", "en": "Print all rows"}}
  ```
- NEVER edit `static/js/i18n.js` (I merge keys myself), `base.html`, any template, any Python file, or another agent's JSON. No commit.

## WHAT TO TRANSLATE
- Alert/confirm/SweetAlert titles, messages, button labels
- Table/column labels, option text, placeholders that are UI wording
- Tooltips, status badges, loading/error messages
- Reuse English keys already in `static/js/i18n.js` translations (Save, Cancel, Delete, Edit, View, Back, Search, Loading, Processing, Success, Error, Warning, Yes, No, OK, Close, Confirm...). Do NOT re-add those keys to your JSON.

## DO NOT TRANSLATE
- Arabic comments (`// ...`, `/* ... */`)
- Arabic-Indic digit placeholder strings like `٠١٢٣٤٥٦٧٨٩` (input masks)
- Data values coming from the server/API, CSS classes, IDs, JS variable/function names, URLs
- Numbers, currency codes, SKUs
- Strings that are already inside `t('...')`

## CRITICAL SAFETY
- Only change the string literal itself; keep surrounding quotes, concatenation and syntax intact.
- If a string is embedded in a larger template literal, replace just the Arabic part with `${t('Key')}` carefully, or leave it and report it.
- Do not change any logic, conditions, or DOM selectors.

## VERIFY
- `node --check <each assigned file>` (if node exists) or at minimum a careful read.
- Confirm every `t('Key')` you added has an entry in your JSON or in i18n.js.
- Report: files changed, keys added, strings left intentionally.
