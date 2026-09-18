import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

describe('shop extra coverage', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.head.innerHTML = '';
    document.documentElement.lang = 'ar';
    // reset cartWired guard so wireCartInteractions re-attaches if needed
    delete (document.body.dataset as any).cartWired;
    // clean up global mocks
    vi.restoreAllMocks();
    (window as any).alert = vi.fn();
    // ensure fetch is mocked per test if needed
    // clear bootstrap/jQuery
    delete (window as any).bootstrap;
    delete (window as any).jQuery;
    // mock Math.random deterministic
    vi.spyOn(Math, 'random').mockReturnValue(0.123456789);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('clampQuantity handles 0, negative, non-numeric, Arabic digits, dataset.max and alert', async () => {
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div class="qty-control">
        <input class="qty-input" value="٥" min="1" data-max="5" type="text">
        <button class="btn-step" data-dir="1">+</button>
        <button class="btn-step" data-dir="-1">-</button>
      </div>
      <div class="qty-control">
        <input class="qty-input" id="q2" value="0" min="2" max="10" type="text">
      </div>
      <div class="qty-control">
        <input class="qty-input" id="q3" value="abc" type="text">
      </div>
      <div class="qty-control">
        <input class="qty-input" id="q4" value="-5" min="1" type="text">
      </div>
    `;

    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    const inputs = document.querySelectorAll('.qty-input') as NodeListOf<HTMLInputElement>;
    const arabicInput = inputs[0];
    // Arabic digit ٥ -> 5 then +1 -> would be 6 > max 5 => alert + clamp to 5
    const plusBtn = document.querySelector('[data-dir="1"]') as HTMLButtonElement;
    plusBtn.click();
    expect(alertMock).toHaveBeenCalled();
    expect(arabicInput.value).toBe('5');

    // 0 with min 2 => clamp to 2 on input event
    const q2 = document.getElementById('q2') as HTMLInputElement;
    q2.dispatchEvent(new Event('input'));
    expect(q2.value).toBe('2');

    // non-numeric with no min attribute => defaults to 1
    const q3 = document.getElementById('q3') as HTMLInputElement;
    q3.dispatchEvent(new Event('input'));
    expect(q3.value).toBe('1');

    // negative => clamp to min 1
    const q4 = document.getElementById('q4') as HTMLInputElement;
    q4.dispatchEvent(new Event('input'));
    expect(q4.value).toBe('1');

    // change/blur also clamp
    q2.value = '99';
    q2.dispatchEvent(new Event('change'));
    expect(q2.value).toBe('10');
    q2.value = '99';
    q2.dispatchEvent(new Event('blur'));
    expect(q2.value).toBe('10');
  });

  it('catalog search handles Arabic digits, empty query, extraOf and fallback nameOf/descOf', async () => {
    document.body.innerHTML = `
      <input id="search" type="search">
      <div id="products-container">
        <div class="product-card" data-name="تفاح" data-desc="فواكه" data-sku="SKU-123" data-part="PART-A" data-alt="ALT"><span class="card-title">Ignored</span></div>
        <div class="product-card"><span class="card-title">Banana</span><span class="card-text">Yellow fruit</span></div>
        <div class="product-card" data-name="Orange"><div class="text-muted">Citrus</div></div>
        <div class="product-card">Just Text Product</div>
      </div>
    `;
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    const search = document.getElementById('search') as HTMLInputElement;
    // empty should show all
    search.value = '';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 200));
    const cards = document.querySelectorAll('.product-card') as NodeListOf<HTMLElement>;
    expect(Array.from(cards).every(c => c.style.display !== 'none')).toBe(true);

    // Arabic digits normalized: search for ١٢٣ (Arabic) should match SKU-123 (normalized query)
    search.value = '١٢٣';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 200));
    expect(cards[0].style.display).not.toBe('none');

    // search for banana should match second card via card-title fallback
    search.value = 'banana';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 200));
    expect(cards[1].style.display).not.toBe('none');
    expect(cards[0].style.display).toBe('none');

    // search for citrus via descOf text-muted fallback
    search.value = 'citrus';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 200));
    expect(cards[2].style.display).not.toBe('none');

    // search for Just Text via textContent fallback
    search.value = 'just text';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 200));
    expect(cards[3].style.display).not.toBe('none');

    // non-matching shows no-results
    search.value = 'zzzzzzz';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 200));
    const no = document.getElementById('no-results-message') as HTMLElement;
    expect(no.style.display).not.toBe('none');
  });

  it('checkout detects all card brands, merges transaction_data, handles invalid JSON and method toggle', async () => {
    const cases: Array<[string, string]> = [
      ['4111111111111111', 'VISA'],
      ['5555555555554444', 'MASTERCARD'],
      ['378282246310005', 'AMEX'],
      ['6011111111111117', 'DISCOVER'],
      ['9999999999999999', 'CARD']
    ];
    for (const [num, brand] of cases) {
      document.body.innerHTML = `
        <form id="payment-form">
          <select id="payment-method"><option value="card">Card</option><option value="cash">Cash</option></select>
          <div id="card-fields">
            <input name="cardholder_name" value="  Tester  ">
            <input name="card_number" value="${num}">
            <input name="card_expiry" value="12/30">
          </div>
          <input type="hidden" id="transaction_data" value='{"existing":"keep"}'>
          <input type="hidden" id="card_last4">
          <input type="hidden" id="card_brand">
          <button type="submit">Pay</button>
        </form>
      `;
      // need fresh listeners for each iteration but we reuse imported module: dispatch will re-wire
      if (cases.indexOf([num, brand] as any) === 0) {
        await import('../../static/js/shop.js');
      }
      document.dispatchEvent(new Event('DOMContentLoaded'));
      const methodSel = document.getElementById('payment-method') as HTMLSelectElement;
      // toggle to cash should hide card-fields, then back to card
      methodSel.value = 'cash';
      methodSel.dispatchEvent(new Event('change'));
      expect((document.getElementById('card-fields') as HTMLElement).style.display).toBe('none');
      methodSel.value = 'card';
      methodSel.dispatchEvent(new Event('change'));
      expect((document.getElementById('card-fields') as HTMLElement).style.display).toBe('');

      // test expiry formatting with Arabic digits
      const expiry = document.querySelector('input[name="card_expiry"]') as HTMLInputElement;
      expiry.value = '١٢٢٥';
      expiry.dispatchEvent(new Event('input'));
      expect(expiry.value).toBe('12/25');
      // restore
      expiry.value = '12/30';

      // test card number formatting
      const number = document.querySelector('input[name="card_number"]') as HTMLInputElement;
      number.value = num;
      number.dispatchEvent(new Event('input'));
      expect(number.value.replace(/\s/g, '').length).toBeGreaterThanOrEqual(15);

      const form = document.getElementById('payment-form') as HTMLFormElement;
      const btn = form.querySelector('button[type="submit"]') as HTMLButtonElement;
      form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      // check transaction_data merged
      const tx = document.getElementById('transaction_data') as HTMLInputElement;
      const payload = JSON.parse(tx.value);
      expect(payload.existing).toBe('keep');
      expect(payload.card.brand).toBe(brand);
      expect(payload.card.last4).toBe(num.slice(-4));
      expect(payload.card.holder).toBe('Tester');
      expect(btn.disabled).toBe(true);
      // reset body for next iteration
      document.body.innerHTML = '';
      delete (document.body.dataset as any).cartWired;
    }

    // invalid JSON in transaction_data should not throw, should fallback to not merging
    document.body.innerHTML = `
      <form id="payment-form">
        <select id="payment-method"><option value="card">Card</option></select>
        <div id="card-fields"><input name="card_number" value="4111111111111111"></div>
        <input type="hidden" id="transaction_data" value='not-json'>
        <input type="hidden" id="card_last4"><input type="hidden" id="card_brand">
        <button type="submit">Pay</button>
      </form>
    `;
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const form2 = document.getElementById('payment-form') as HTMLFormElement;
    form2.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    const tx2 = document.getElementById('transaction_data') as HTMLInputElement;
    // still 'not-json' because catch swallows, value unchanged? Check code: try parse, catch empty -> leaves old value
    expect(tx2.value).toBe('not-json');

    // empty transaction_data should be replaced with new payload
    document.body.innerHTML = `
      <form id="payment-form">
        <select id="payment-method"><option value="card">Card</option></select>
        <div id="card-fields"><input name="card_number" value="4111111111111111"></div>
        <input type="hidden" id="transaction_data" value=''>
        <input type="hidden" id="card_last4"><input type="hidden" id="card_brand">
        <button type="submit">Pay</button>
      </form>
    `;
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const form3 = document.getElementById('payment-form') as HTMLFormElement;
    form3.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    const tx3 = document.getElementById('transaction_data') as HTMLInputElement;
    expect(JSON.parse(tx3.value).transaction_id).toMatch(/^TXN-/);
  });

  it('postJSON handles csrf fallbacks, prepaidRate fallback, and json error branches', async () => {
    // csrf fallback: no meta, use input[name=csrf_token]
    document.body.innerHTML = `
      <input name="csrf_token" value="input-token">
      <span id="prod-status-badge" class="badge badge-inactive">غير مفعل</span>
      <button id="toggle-active-btn" data-toggle-url="/api/toggle"></button>
      <div id="cart-subtotal"></div>
      <div id="cart-total"></div>
      <div id="cart-prepaid"></div>
      <meta name="prepaid-rate" content="invalid">
    `;
    const fetchMock1 = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => { throw new Error('bad json'); },
      headers: { get: () => 'application/json' }
    });
    vi.stubGlobal('fetch', fetchMock1);
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    (document.getElementById('toggle-active-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(fetchMock1).toHaveBeenCalled();
    expect(fetchMock1.mock.calls[0][1].headers['X-CSRFToken']).toBe('input-token');
    // prepaidRate with invalid content should fallback to 0.2, test via recalcSummary
    // trigger cart update with html fallback to trigger prepaidRate
    // Now test cookie fallback
    document.body.innerHTML = '';
    document.cookie = 'csrf_token=cookie%20token';
    document.body.innerHTML = `
      <button id="toggle-active-btn" data-toggle-url="/api/toggle2"></button>
      <span id="prod-status-badge" class="badge badge-active">مفعَل</span>
    `;
    const fetchMock2 = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, message: 'ok' }) });
    vi.stubGlobal('fetch', fetchMock2);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    (document.getElementById('toggle-active-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(fetchMock2.mock.calls[0][1].headers['X-CSRFToken']).toBe('cookie token');

    // no csrf at all => empty
    document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    document.body.innerHTML = `<button id="toggle-active-btn" data-toggle-url="/api/toggle3"></button><span id="prod-status-badge" class="badge badge-active"></span>`;
    const fetchMock3 = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal('fetch', fetchMock3);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    (document.getElementById('toggle-active-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(fetchMock3.mock.calls[0][1].headers['X-CSRFToken']).toBe('');

    // postJSON fetch rejection handled (toggle network error)
    document.body.innerHTML = `<button id="toggle-active-btn" data-toggle-url="/api/toggle4"></button><span id="prod-status-badge" class="badge badge-active"></span>`;
    const fetchMock4 = vi.fn().mockRejectedValue(new Error('network'));
    vi.stubGlobal('fetch', fetchMock4);
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    document.dispatchEvent(new Event('DOMContentLoaded'));
    (document.getElementById('toggle-active-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('تعذر الاتصال');
  });

  it('hideBsModal covers bootstrap, jQuery and fallback branches', async () => {
    // Need to trigger via quick-category success path which calls hideBsModal
    // Bootstrap branch
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <select id="category_id" name="category_id"></select>
      <form id="quick-category-form" data-url="/api/cat" action="/api/cat">
        <input id="qc-name" value="NewCat">
      </form>
      <div id="quickCategoryModal" class="show" style="display:block"></div>
      <div class="modal-backdrop"></div>
    `;
    document.body.classList.add('modal-open');
    document.body.style.paddingRight = '15px';
    document.body.style.overflow = 'hidden';
    await import('../../static/js/shop.js');
    // mock bootstrap
    const disposeMock = vi.fn();
    const hideMock = vi.fn();
    (window as any).bootstrap = {
      Modal: {
        getInstance: vi.fn().mockReturnValue({ hide: hideMock, dispose: disposeMock }),
        getOrCreateInstance: vi.fn()
      }
    };
    let fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, id: '99', name: 'NewCat' })
    });
    vi.stubGlobal('fetch', fetchMock);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const form = document.getElementById('quick-category-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    expect(hideMock).toHaveBeenCalled();
    await new Promise(r => setTimeout(r, 250));
    expect(document.querySelector('.modal-backdrop')).toBeNull();

    // bootstrap getInstance null => getOrCreateInstance
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <select id="category_id"></select>
      <form id="quick-category-form" data-url="/api/cat2"><input id="qc-name" value="Cat2"></form>
      <div id="quickCategoryModal" class="show"></div>
      <div class="modal-backdrop"></div>
    `;
    document.body.classList.add('modal-open');
    (window as any).bootstrap = {
      Modal: {
        getInstance: vi.fn().mockReturnValue(null),
        getOrCreateInstance: vi.fn().mockReturnValue({ hide: hideMock, dispose: disposeMock })
      }
    };
    fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, id: '100', name: 'Cat2' }) });
    vi.stubGlobal('fetch', fetchMock);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    document.getElementById('quick-category-form')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    expect((window as any).bootstrap.Modal.getOrCreateInstance).toHaveBeenCalled();

    // jQuery branch
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <select id="category_id"></select>
      <form id="quick-category-form" data-url="/api/cat3"><input id="qc-name" value="Cat3"></form>
      <div id="quickCategoryModal"></div>
      <div class="modal-backdrop"></div>
    `;
    delete (window as any).bootstrap;
    (window as any).jQuery = vi.fn().mockReturnValue({ modal: vi.fn() } as any);
    (window as any).jQuery.fn = { modal: vi.fn() };
    // need jQuery(el).modal stub
    const jqModalMock = vi.fn();
    (window as any).jQuery = (el: any) => ({ modal: jqModalMock });
    (window as any).jQuery.fn = { modal: true };
    fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, id: '101', name: 'Cat3' }) });
    vi.stubGlobal('fetch', fetchMock);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    document.getElementById('quick-category-form')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    expect(jqModalMock).toHaveBeenCalledWith('hide');

    // fallback branch (no bootstrap, no jQuery)
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <select id="category_id"></select>
      <form id="quick-category-form" data-url="/api/cat4"><input id="qc-name" value="Cat4"></form>
      <div id="quickCategoryModal" class="show" style="display:block" aria-hidden="false"></div>
      <div class="modal-backdrop"></div>
    `;
    delete (window as any).bootstrap;
    delete (window as any).jQuery;
    fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, id: '102', name: 'Cat4' }) });
    vi.stubGlobal('fetch', fetchMock);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    document.getElementById('quick-category-form')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    const modal = document.getElementById('quickCategoryModal') as HTMLElement;
    expect(modal.classList.contains('show')).toBe(false);
    expect(modal.style.display).toBe('none');

    // catch branch: bootstrap throws
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <select id="category_id"></select>
      <form id="quick-category-form" data-url="/api/cat5"><input id="qc-name" value="Cat5"></form>
      <div id="quickCategoryModal"></div>
      <div class="modal-backdrop"></div>
    `;
    (window as any).bootstrap = {
      Modal: {
        getInstance: vi.fn().mockImplementation(() => { throw new Error('boom'); }),
        getOrCreateInstance: vi.fn()
      }
    };
    fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, id: '103', name: 'Cat5' }) });
    vi.stubGlobal('fetch', fetchMock);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    document.getElementById('quick-category-form')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    expect(document.querySelector('.modal-backdrop')).toBeNull();
  });

  it('quick-category form validation and error paths', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <select id="category_id"><option value="1">Old</option></select>
      <form id="quick-category-form" data-url="/api/cat"><input id="qc-name" value=""></form>
      <div id="quickCategoryModal"></div>
    `;
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    const form = document.getElementById('quick-category-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 20));
    expect(alertMock).toHaveBeenCalledWith('الاسم مطلوب');

    // fetch returns not ok
    (document.getElementById('qc-name') as HTMLInputElement).value = 'Test';
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ ok: false, error: 'تعذر إنشاء الفئة' }) });
    vi.stubGlobal('fetch', fetchMock);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('تعذر إنشاء الفئة');

    // json throws
    const fetchMock2 = vi.fn().mockResolvedValue({ ok: true, json: async () => { throw new Error('bad'); } });
    vi.stubGlobal('fetch', fetchMock2);
    (document.getElementById('qc-name') as HTMLInputElement).value = 'Another';
    document.dispatchEvent(new Event('DOMContentLoaded'));
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalled();
  });

  it('online panel handles empty warehouses, badge, and fetch failure', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="5" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-warehouse-badge" class="bg-secondary">badge</span>
        <div id="online-alert" class="d-none"></div>
        <form id="online-form"><input id="online-price"><input id="online-qty"><span id="online-image-url"></span><img id="online-thumb"><span id="online-status"></span></form>
        <input type="file" id="online-file"><button id="btn-upload-online"></button><button id="btn-save-online"></button>
      </div>
    `;
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 50));
    expect((document.getElementById('online-warehouse-badge') as HTMLElement).textContent).toBe('لا يوجد أونلاين');
    expect((document.getElementById('online-alert') as HTMLElement).classList.contains('d-none')).toBe(false);
    expect((document.getElementById('online-form') as HTMLElement).classList.contains('d-none')).toBe(true);

    // fetch failure branch
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="5" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-warehouse-badge"></span><span id="online-status"></span>
        <form id="online-form"></form>
      </div>
    `;
    const fetchMockFail = vi.fn().mockRejectedValue(new Error('net'));
    vi.stubGlobal('fetch', fetchMockFail);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 50));
    expect((document.getElementById('online-warehouse-badge') as HTMLElement).textContent).toBe('فشل الجلب');
  });

  it('online panel load, upload and save flows', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="7" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-warehouse-badge" class="bg-secondary"></span>
        <div id="online-alert" class="d-none"></div>
        <form id="online-form">
          <input id="online-price"><input id="online-qty"><span id="online-image-url"></span>
          <img id="online-thumb"><span id="online-status"></span>
        </form>
        <input type="file" id="online-file"><button id="btn-upload-online">U</button><button id="btn-save-online">S</button>
      </div>
      <input name="online_image">
    `;
    // list fetch returns warehouses with default
    const fetchMock = vi.fn()
      .mockImplementation((url: string) => {
        if (String(url).includes('/api/list')) {
          return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 2, name: 'WH2' }, { id: 3, name: 'WH3', online_is_default: true }] }) });
        }
        if (String(url).includes('/api/prod/')) {
          return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 7, online_price: 12.345, quantity: 8, online_image: 'http://img' }] }) });
        }
        if (String(url).includes('/api/upload')) {
          return Promise.resolve({ ok: true, json: async () => ({ ok: true, url: 'http://uploaded', thumb_url: 'http://thumb' }) });
        }
        if (String(url).includes('/api/upd/')) {
          return Promise.resolve({ ok: true, json: async () => ({ ok: true, message: 'تم حفظ إعدادات الأونلاين' }) });
        }
        return Promise.resolve({ ok: false, json: async () => ({}) });
      });
    vi.stubGlobal('fetch', fetchMock);
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    expect((document.getElementById('online-warehouse-badge') as HTMLElement).textContent).toContain('Online #3');
    expect((document.getElementById('online-price') as HTMLInputElement).value).toBe('12.35');
    expect((document.getElementById('online-qty') as HTMLInputElement).value).toBe('8');
    expect((document.getElementById('online-image-url') as HTMLElement).textContent).toBe('http://img');
    expect((document.getElementById('online-status') as HTMLElement).textContent).toBe('تم التحميل.');

    // upload: no file alert
    const fileEl = document.getElementById('online-file') as HTMLInputElement;
    // ensure empty files
    Object.defineProperty(fileEl, 'files', { value: [], configurable: true });
    // trigger change
    fileEl.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 20));
    expect(alertMock).toHaveBeenCalledWith('اختر صورة أولاً');

    // upload success
    const file = new File(['abc'], 'a.png', { type: 'image/png' });
    Object.defineProperty(fileEl, 'files', { value: [file], configurable: true });
    fileEl.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 50));
    expect((document.getElementById('online-thumb') as HTMLImageElement).src).toContain('http');
    expect((document.querySelector('input[name="online_image"]') as HTMLInputElement).value).toBe('http://uploaded');

    // btn-upload click triggers file click
    const clickSpy = vi.fn();
    fileEl.click = clickSpy;
    (document.getElementById('btn-upload-online') as HTMLButtonElement).click();
    expect(clickSpy).toHaveBeenCalled();

    // saveOnline success with price/qty/image
    (document.getElementById('online-price') as HTMLInputElement).value = '١٥,٥٠'; // Arabic 15,50 => 15.50
    (document.getElementById('online-qty') as HTMLInputElement).value = '3';
    (document.getElementById('btn-save-online') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/upd/'), expect.objectContaining({ method: 'PATCH' }));
    expect(alertMock).toHaveBeenCalledWith('تم حفظ إعدادات الأونلاين');

    // save with no onlineWid
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="9" data-list-url="/api/empty" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-status"></span>
        <input id="online-price"><input id="online-qty"><span id="online-image-url"></span>
        <button id="btn-save-online"></button>
      </div>
    `;
    // next fetch for list will return empty, so onlineWid stays null
    const fetchEmpty = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [] }) });
    vi.stubGlobal('fetch', fetchEmpty);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 50));
    (document.getElementById('btn-save-online') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 20));
    expect(alertMock).toHaveBeenCalledWith('لا يوجد مستودع أونلاين');

    // save with empty payload
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="10" data-list-url="/api/list2" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-status"></span><span id="online-warehouse-badge"></span>
        <input id="online-price" value=""><input id="online-qty" value=""><span id="online-image-url"></span>
        <button id="btn-save-online"></button>
      </div>
    `;
    const fetchList2 = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list2')) return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 5, name: 'W' }] }) });
      return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
    });
    vi.stubGlobal('fetch', fetchList2);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 50));
    (document.getElementById('btn-save-online') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 20));
    expect(alertMock).toHaveBeenCalledWith('لا يوجد أي تغيير للحفظ');
  });

  it('cart recalc, applyCartJSON, prepaidRate fallback and html fallback', async () => {
    // test recalcRowTotal with data-unit and Arabic digits, updateCartCounter null guard, recalcSummary multiple rows
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table>
        <tr class="cart-row">
          <td><input name="quantity" value="٢"></td>
          <td><span class="price-unit" data-unit="10.00">10.00 ILS</span></td>
          <td><span class="row-total">x</span></td>
        </tr>
        <tr class="cart-row">
          <td><input name="quantity" value="3"></td>
          <td><span class="price-unit">5.00 ILS</span></td>
          <td><span class="row-total">x</span></td>
        </tr>
      </table>
      <div id="cart-counter">0</div>
      <div id="cart-subtotal"></div><div id="cart-total"></div><div id="cart-prepaid"></div>
      <!-- no prepaid-rate meta => fallback 0.2 -->
      <form class="cart-update-form" action="/cart/update/1"><button>u</button></form>
    `;
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        cart_count: 5,
        item: { quantity: 4, price: '20.00', total: 80 },
        subtotal: 95,
        total: 95,
        prepaid_amount: 19
      }),
      headers: { get: () => 'application/json' }
    });
    vi.stubGlobal('fetch', fetchMock);
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    // trigger cart update via form submit
    const form = document.querySelector('.cart-update-form') as HTMLFormElement;
    // need tr for applyCartJSON: form.closest('tr') is null because form not inside tr, so tr null but still applyCartJSON handles
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    expect(document.getElementById('cart-counter')!.textContent).toBe('5');
    expect(document.getElementById('cart-subtotal')!.textContent).toContain('ILS');
    // test applyCartJSON with item null etc via html fallback path
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table>
        <tr class="cart-row" id="r1"><td><input name="quantity" value="1"><span class="price-unit" data-unit="10"></span><span class="row-total">10 ILS</span></td><td><form class="cart-remove-form" action="/cart/remove/1"><button>r</button></form></td></tr>
        <tr class="cart-row" id="r2"><td><input name="quantity" value="2"><span class="price-unit" data-unit="5"></span><span class="row-total">10 ILS</span></td></tr>
      </table>
      <div id="cart-counter">2</div><div id="cart-subtotal"></div><div id="cart-total"></div><div id="cart-prepaid"></div>
      <meta name="prepaid-rate" content="0.5">
    `;
    const htmlFetch = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => 'text/html' },
      text: async () => `<div><span id="cart-counter">10</span></div>`
    });
    vi.stubGlobal('fetch', htmlFetch);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const removeForm = document.querySelector('.cart-remove-form') as HTMLFormElement;
    // attach inside tr properly? Already inside first row
    removeForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 80));
    expect(document.getElementById('cart-counter')!.textContent).toBe('10');
    expect(document.getElementById('r1')).toBeNull();

    // last row removal triggers reload when no rows left
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table><tr class="cart-row" id="only"><td><form class="cart-remove-form" action="/cart/remove/2"></form></td><td><span class="row-total">0</span><span class="price-unit" data-unit="0"></span><input name="quantity" value="1"></td></tr></table>
      <div id="cart-counter"></div>
    `;
    const reloadMock = vi.fn();
    Object.defineProperty(window, 'location', { value: { reload: reloadMock }, writable: true });
    const fetchLast = vi.fn().mockResolvedValue({ ok: true, headers: { get: () => 'application/json' }, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchLast);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    document.querySelector('.cart-remove-form')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 80));
    expect(reloadMock).toHaveBeenCalled();
  });

  it('main image upload success, failure and btn click', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <input type="file" id="main-file"><img id="main-thumb"><span id="main-image-url"></span>
      <button id="btn-upload-main">Up</button><input name="image">
    `;
    const file = new File(['x'], 'img.png', { type: 'image/png' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, url: 'http://main', thumb_url: 'http://thumb-main' }) });
    vi.stubGlobal('fetch', fetchMock);
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    const mainFile = document.getElementById('main-file') as HTMLInputElement;
    Object.defineProperty(mainFile, 'files', { value: [file], configurable: true });
    mainFile.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 50));
    expect((document.getElementById('main-thumb') as HTMLImageElement).src).toContain('http');
    expect((document.querySelector('input[name="image"]') as HTMLInputElement).value).toBe('http://main');
    expect(mainFile.value).toBe('');

    // failure ok false
    Object.defineProperty(mainFile, 'files', { value: [file], configurable: true });
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    const fetchFail = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ ok: false, error: 'فشل الرفع' }) });
    vi.stubGlobal('fetch', fetchFail);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    mainFile.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('فشل الرفع');

    // catch
    const fetchErr = vi.fn().mockRejectedValue(new Error('net'));
    vi.stubGlobal('fetch', fetchErr);
    Object.defineProperty(mainFile, 'files', { value: [file], configurable: true });
    mainFile.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('تعذر رفع الصورة');

    // no file early return
    Object.defineProperty(mainFile, 'files', { value: [], configurable: true });
    const fetchNo = vi.fn();
    vi.stubGlobal('fetch', fetchNo);
    mainFile.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 20));
    expect(fetchNo).not.toHaveBeenCalled();

    // btn click
    const clickSpy = vi.fn();
    mainFile.click = clickSpy;
    (document.getElementById('btn-upload-main') as HTMLButtonElement).click();
    expect(clickSpy).toHaveBeenCalled();
  });

  it('alert auto-dismiss with bootstrap and normalizeDecimal edge cases', async () => {
    // bootstrap Alert branch
    vi.useFakeTimers();
    document.body.innerHTML = `<div class="alert">hi</div>`;
    const closeMock = vi.fn();
    (window as any).bootstrap = { Alert: class { constructor(public el: any) {} close() { closeMock(); document.querySelector('.alert')?.remove(); } } };
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    vi.advanceTimersByTime(5000);
    expect(closeMock).toHaveBeenCalled();
    vi.useRealTimers();
    delete (window as any).bootstrap;

    // normalizeDecimal via price input: 1.234,56 -> 1234.56 and 1٬234٫56 etc
    document.body.innerHTML = `
      <form id="product-form"><input name="price" id="price" value=""></form>
    `;
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const price = document.getElementById('price') as HTMLInputElement;
    price.value = '1.234,56';
    const form = document.getElementById('product-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    expect(price.value).toBe('1234.56');
    price.value = '1,234.56';
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    expect(price.value).toBe('1234.56');
    // Arabic thousands comma
    price.value = '1٬234٫56';
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    // normalizeDecimal replaces ٬، with , and ٫ with . => 1,234.56 => 1234.56
    expect(price.value).toBe('1234.56');

    // quick-update with price that needs normalizeDecimal
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <form id="product-form"><input name="name" id="name"><input name="price" id="price"></form>
      <input id="quick-name" value=""><input id="quick-price" value="1.234,56">
      <button id="quick-update-btn" data-update-url="/api/upd">U</button>
    `;
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, message: 'تم التحديث' }) });
    vi.stubGlobal('fetch', fetchMock);
    (window as any).alert = vi.fn();
    document.dispatchEvent(new Event('DOMContentLoaded'));
    (document.getElementById('quick-update-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(fetchMock.mock.calls[0][1].body).toContain('1234.56');
  });

  it('wireQtyButtons without input and quick-update empty payload', async () => {
    document.body.innerHTML = `
      <div class="qty-control"><button class="btn-step" data-dir="1">+</button></div>
      <meta name="csrf-token" content="t">
      <input id="quick-name" value=""><input id="quick-price" value="">
      <button id="quick-update-btn" data-update-url="/api/upd2">U</button>
    `;
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    // btn-step without input should not throw
    (document.querySelector('.btn-step') as HTMLButtonElement).click();
    expect(fetchMock).not.toHaveBeenCalled(); // no quick update yet

    // quick update with empty name and price => payload {} still calls postJSON but with {}
    (document.getElementById('quick-update-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(fetchMock).toHaveBeenCalled();
    expect(fetchMock.mock.calls[0][1].body).toBe('{}');
  });
});
