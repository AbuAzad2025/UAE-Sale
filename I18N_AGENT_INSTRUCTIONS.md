# I18N Translation Agent — STRICT RULES

Working directory: `D:\recovers\data\UAE-Sale` (Windows, PowerShell). Python is on PATH.

## GOAL
Convert hardcoded Arabic **UI text** in the assigned templates into `{{ t('English key') }}` calls, so the language switch (Arabic/English) actually translates the interface.

The `t()` helper reads `session['language']`:
- Arabic mode → returns the `ar` value from the dictionary
- English mode → returns the key itself (which must be correct English)

## STRICT FILE OWNERSHIP (no conflicts — violating this breaks other agents)
1. Edit **ONLY** the template files listed in your assignment.
2. Write your new translation keys in **ONLY** `utils/i18n_keys/agent_XX.py` (the exact number given to you). Create it with:
   ```python
   TRANSLATIONS = {
       "Invoice": {"ar": "الفاتورة", "en": "Invoice"},
   }
   ```
3. **NEVER** edit `utils/i18n.py`, any other `agent_*.py`, any other template, any `.py` route/service/model, or git. Do not commit. Do not run the app. Do not touch the database.

## WHAT TO TRANSLATE (UI text only)
- Table headers: `<th>الفاتورة</th>` → `<th>{{ t('Invoice') }}</th>`
- Labels/buttons/headings/paragraphs: `<label>`, `<button>`, `<h1>`..`<h6>`, `<p>`, `<span>`, `<a>` when the text is static UI wording
- `<option>` visible text (not the `value` attribute)
- HTML attributes meant for humans: `placeholder="..."`, `title="..."`, `aria-label="..."`
- `<title>` and `{% block title %}` / `{% block page_title %}` static Arabic parts (keep dynamic `{{ ... }}` parts)
- Static Arabic fallback literals like `'أزاد'` in `current_tenant.name_ar or 'أزاد'` → `{{ t('Azad') }}`
- Bilingual labels such as `الموردين (Suppliers)` → `{{ t('Suppliers') }}` with `{"ar":"الموردين","en":"Suppliers"}` (drop the parenthetical)
- User-facing strings inside `<script>` blocks: inject with `{{ t('Key')|tojson }}` where a JS string is expected, e.g. `typeLabel = {{ t('Supplier')|tojson }};`

## WHAT NOT TO TRANSLATE
- Data values from the database: `{{ product.name }}`, `{{ display_name(x) }}`, `{{ customer.name_ar }}`, invoice numbers, user names
- Existing `t('...')` calls — leave them untouched
- Anything inside `{{ ... }}` Jinja expressions or `{% ... %}` control structures (except static string literals as noted above)
- CSS classes, element IDs, JS variable/function names, route names, URLs, form `name=` attributes
- Numbers, dates, currency codes (ILS/USD), SKUs, percentages
- SQL, JSON keys, API payload keys

## KEY DICTIONARY RULES
- Read `utils/i18n.py` `TRANSLATIONS` first and **reuse an existing key** whenever the English phrase already exists (e.g. Save, Cancel, Date, Amount, Status, Total, Products, Customers, Suppliers, Reports, Ledger, Sales, Purchases, Trial Balance, Income Statement, Balance Sheet, Print, Export, Search, Filter...).
- Use natural, concise English for new keys. Same English key = same Arabic value everywhere.
- Value format: `{"ar": "<the EXACT original Arabic text>", "en": "<the English key or better English wording>"}`.
- If the English key contains an apostrophe, use double quotes for the Python key and `{{ t("...") }}` in the template.
- Do not add keys you do not use.

## VERIFICATION (must run before finishing)
1. Jinja parse ALL your assigned templates:
   ```bash
   python -c "from jinja2 import Environment,FileSystemLoader; env=Environment(loader=FileSystemLoader('templates')); import sys; [env.parse(open(p,encoding='utf-8').read()) for p in sys.argv[1:]]; print('OK')" <your files>
   ```
2. Compile your keys file: `python -m py_compile utils/i18n_keys/agent_XX.py`
3. Confirm you did not modify any file outside your ownership.

## REPORT AT THE END
- Files changed (count and list)
- Number of keys added
- Any template you could not safely translate and why
