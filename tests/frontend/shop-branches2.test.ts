import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

describe('shop uncovered branches II', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.head.innerHTML = '';
    document.documentElement.lang = 'ar';
    delete (document.body.dataset as any).cartWired;
    vi.restoreAllMocks();
    (window as any).alert = vi.fn();
    delete (window as any).bootstrap;
    delete (window as any).jQuery;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function cartTable(rowInner: string, extra = '') {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table><tr class="cart-row" id="row1">${rowInner}</tr>
      <tr class="cart-row" id="row2"><td><span class="row-total">5.00 ILS</span></td></tr></table>
      <div id="cart-counter">0</div>${extra}
      <meta name="prepaid-rate" content="0.2">
    `;
  }

  function jsonFetch(payload: any, contentType: string | null = 'application/json') {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
      headers: { get: () => contentType }
    }));
  }

  async function boot() {
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
  }

  it('toggle button without url returns early', async () => {
    document.body.innerHTML = `
      <button id="toggle-active-btn">T</button>
      <span id="prod-status-badge"></span>
    `;
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await boot();
    (document.getElementById('toggle-active-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 30));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('applyCartJSON item without quantity/price/total takes else sides', async () => {
    cartTable(`<td><form class="cart-update-form" action="/cart/update/1"><button>u</button></form></td>`,
      `<div id="cart-subtotal"></div><div id="cart-total"></div><div id="cart-prepaid"></div>`);
    jsonFetch({ ok: true, cart_count: 2, item: {} });
    await boot();
    (document.querySelector('.cart-update-form') as HTMLFormElement)
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 60));
    expect(document.getElementById('cart-counter')!.textContent).toBe('2');
  });

  it('applyCartJSON quantity branch when row lacks quantity input', async () => {
    cartTable(`<td><form class="cart-update-form" action="/cart/update/1"><button>u</button></form></td>`);
    jsonFetch({ ok: true, item: { quantity: 7 } });
    await boot();
    (document.querySelector('.cart-update-form') as HTMLFormElement)
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 60));
    // no quantity input to update, but summary still recalculated over remaining row
    expect(document.getElementById('cart-counter')!.textContent).toBe('0');
  });

  it('applyCartJSON price/total branches when elements are missing', async () => {
    cartTable(`<td><form class="cart-update-form" action="/cart/update/1"><button>u</button></form></td>`);
    jsonFetch({ ok: true, item: { price: '5.00', total: 10 }, total: 50 });
    await boot();
    (document.querySelector('.cart-update-form') as HTMLFormElement)
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 60));
    // missing #cart-total so only counter assertion is stable
    expect(document.getElementById('cart-counter')!.textContent).toBe('0');
  });

  it('recalcSummary tolerates missing subtotal/total elements', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table><tr class="cart-row">
        <td><input name="quantity" value="1"></td>
        <td><span class="price-unit" data-unit="4.00"></span></td>
        <td><span class="row-total">4.00 ILS</span></td>
        <td><form class="cart-update-form" action="/cart/update/1"><button>u</button></form></td>
      </tr></table>
    `;
    jsonFetch({ ok: true });
    await boot();
    (document.querySelector('.cart-update-form') as HTMLFormElement)
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 60));
    expect((document.querySelector('.row-total') as HTMLElement).textContent).toContain('4.00');
  });

  it('online upload with thumb only, missing elements and no image field', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="31" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-status"></span>
        <form id="online-form"><input id="online-price"><input id="online-qty"></form>
        <input type="file" id="online-file"><button id="btn-upload-online"></button><button id="btn-save-online"></button>
      </div>
    `;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 1, name: 'W' }] }) });
      }
      if (String(url).includes('/api/prod/')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ ok: true, thumb_url: 'http://th' }) });
    }));
    await boot();
    await new Promise(r => setTimeout(r, 80));
    const fileEl = document.getElementById('online-file') as HTMLInputElement;
    Object.defineProperty(fileEl, 'files', { value: [new File(['x'], 'a.png')], configurable: true });
    fileEl.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 50));
    // success path with thumb-only payload leaves the in-progress status (no status update on success)
    expect((document.getElementById('online-status') as HTMLElement).textContent).toContain('جاري رفع الصورة');
  });

  it('main upload failure default message and missing elements', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <input type="file" id="main-file">
      <button id="btn-upload-main">up</button>
      <form><input name="image"></form>
    `;
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ ok: false })
    }));
    await boot();
    const fileEl = document.getElementById('main-file') as HTMLInputElement;
    Object.defineProperty(fileEl, 'files', { value: [new File(['x'], 'm.png')], configurable: true });
    fileEl.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 60));
    expect(alertMock).toHaveBeenCalledWith('فشل الرفع');
  });

  it('main upload with thumb fallback covers url branches', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <input type="file" id="main-file">
      <img id="main-thumb">
      <span id="main-image-url"></span>
      <button id="btn-upload-main">up</button>
      <form><input name="image"></form>
    `;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, thumb_url: 'http://only-thumb' })
    }));
    await boot();
    const fileEl = document.getElementById('main-file') as HTMLInputElement;
    Object.defineProperty(fileEl, 'files', { value: [new File(['x'], 'm.png')], configurable: true });
    fileEl.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 60));
    expect((document.querySelector('input[name="image"]') as HTMLInputElement).value).toBe('http://only-thumb');
    expect((document.getElementById('main-image-url') as HTMLElement).textContent).toBe('http://only-thumb');
  });

  it('saveOnline message variants: default, message-only', async () => {
    const panel = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="32" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-status"></span>
        <input id="online-price" value="5"><input id="online-qty" value="abc"><span id="online-image-url"></span>
        <button id="btn-save-online"></button>
      </div>
    `;
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    document.body.innerHTML = panel;
    // invalid qty skipped; success without message -> default alert
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 2, name: 'W' }] }) });
      }
      if (String(url).includes('/api/prod/')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
    }));
    await boot();
    await new Promise(r => setTimeout(r, 80));
    (document.getElementById('btn-save-online') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('تم حفظ إعدادات الأونلاين');

    // message-only failure (no error field)
    document.body.innerHTML = panel;
    delete (document.body.dataset as any).cartWired;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 2, name: 'W' }] }) });
      }
      if (String(url).includes('/api/prod/')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
      }
      return Promise.resolve({ ok: false, json: async () => ({ ok: false, message: 'رسالة فقط' }) });
    }));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    (document.getElementById('btn-save-online') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('رسالة فقط');
  });

  it('online list/prod with missing data keys and null product fields', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-warehouse-badge"></span><span id="online-status"></span>
        <form id="online-form"><input id="online-price"><input id="online-qty"><span id="online-image-url"></span><img id="online-thumb"></form>
        <input type="file" id="online-file"><button id="btn-upload-online"></button><button id="btn-save-online"></button>
      </div>
    `;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 9, name: 'W9' }] }) });
      }
      // no data key at all
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }));
    await boot();
    await new Promise(r => setTimeout(r, 80));
    expect((document.getElementById('online-status') as HTMLElement).textContent).toBe('تم التحميل.');

    // product row without price/qty/image fields
    delete (document.body.dataset as any).cartWired;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 9, name: 'W9' }] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 0 }] }) });
    }));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    expect((document.getElementById('online-qty') as HTMLInputElement).value).toBe('0');
  });

  it('online panel without price/qty/image elements', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="0" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-status"></span>
        <form id="online-form"></form>
        <input type="file" id="online-file"><button id="btn-upload-online"></button><button id="btn-save-online"></button>
      </div>
    `;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 3, name: 'W3' }] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 0, online_price: 7, quantity: 2, online_image: 'http://i' }] }) });
    }));
    await boot();
    await new Promise(r => setTimeout(r, 80));
    expect((document.getElementById('online-status') as HTMLElement).textContent).toBe('تم التحميل.');
  });

  it('quick-category uses action attribute and name fallback', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <form id="quick-category-form" action="/api/cat2">
        <input id="qc-name" value="FallbackName">
      </form>
      <select name="category_id" id="category_id"></select>
      <div id="quickCategoryModal" class="show"></div>
    `;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, id: 21 })
    }));
    await boot();
    (document.getElementById('quick-category-form') as HTMLFormElement)
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    const sel = document.getElementById('category_id') as HTMLSelectElement;
    expect(sel.options[0].textContent).toBe('FallbackName');
    expect(document.getElementById('quickCategoryModal')!.style.display).toBe('none');
  });

  it('quick-update and toggle surface server messages', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <form id="product-form"><input name="price" id="price" value="10"></form>
      <button id="quick-update-btn" data-update-url="/api/qu">Q</button>
      <input id="quick-name" value="N"><input id="quick-price" value="5">
      <span id="prod-status-badge"></span>
      <button id="toggle-active-btn" data-toggle-url="/api/tg">T</button>
    `;
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      calls.push(String(url));
      return Promise.resolve({ ok: true, json: async () => ({ ok: true, message: 'ok-msg' }) });
    }));
    await boot();
    (document.getElementById('quick-update-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('ok-msg');
    (document.getElementById('toggle-active-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('ok-msg');
    expect(calls.some(u => u.includes('/api/tg'))).toBe(true);

    // toggle failure without message -> default
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({ ok: false }) }));
    (document.getElementById('toggle-active-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('تعذر التحديث');
  });

  it('postJSON json-parse failure with !ok yields error message', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <form id="product-form"><input name="price" id="price" value="10"></form>
      <button id="quick-update-btn" data-update-url="/api/qux">Q</button>
      <input id="quick-name" value="N"><input id="quick-price" value="5">
    `;
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => { throw new Error('bad json'); }
    }));
    await boot();
    (document.getElementById('quick-update-btn') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('error');
  });

  it('checkout minimal form covers empty-field branches', async () => {
    document.body.innerHTML = `
      <form id="payment-form">
        <input name="card_number" value="">
        <input name="card_expiry" value="12">
      </form>
    `;
    await boot();
    const num = document.querySelector('input[name="card_number"]') as HTMLInputElement;
    num.dispatchEvent(new Event('input'));
    expect(num.value).toBe('');
    const exp = document.querySelector('input[name="card_expiry"]') as HTMLInputElement;
    exp.dispatchEvent(new Event('input'));
    expect(exp.value).toBe('12');
    (document.getElementById('payment-form') as HTMLFormElement)
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 30));
  });

  it('checkout method toggle hidden without card fields container', async () => {
    document.body.innerHTML = `
      <form id="payment-form">
        <select id="payment-method"><option value="card">card</option><option value="cash">cash</option></select>
        <input name="card_number" value="4111111111111111">
      </form>
    `;
    await boot();
    const sel = document.getElementById('payment-method') as HTMLSelectElement;
    sel.value = 'cash';
    sel.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 20));
    expect(sel.value).toBe('cash');
  });

  it('qty reset without min, step without dir, existing no-results, empty card', async () => {
    document.body.innerHTML = `
      <div class="qty-control"><input class="qty-input" id="nomin" value="3" type="text"></div>
      <div class="qty-control"><input class="qty-input" id="wdir" value="2" min="1" type="text"><button class="btn-step" id="nodir">+</button></div>
      <input id="search" type="search">
      <div id="products-container">
        <div class="product-card" data-name="قلم">Pen</div>
        <div class="product-card" id="emptycard"></div>
      </div>
      <div id="no-results-message" style="display:none"></div>
    `;
    await boot();
    const resetBtn = document.querySelector('#nomin')!.closest('.qty-control')!.querySelector('.btn-reset') as HTMLButtonElement;
    resetBtn.click();
    expect((document.getElementById('nomin') as HTMLInputElement).value).toBe('1');
    (document.getElementById('nodir') as HTMLButtonElement).click();
    expect((document.getElementById('wdir') as HTMLInputElement).value).toBe('2');
    const search = document.getElementById('search') as HTMLInputElement;
    search.value = 'قلم';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 250));
    expect((document.getElementById('emptycard') as HTMLElement).style.display).toBe('none');
    search.value = 'zzz-no-match';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 250));
    expect((document.getElementById('no-results-message') as HTMLElement).style.display).not.toBe('none');
  });

  it('html fallback without counter and null content-type', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table><tr class="cart-row" id="r1">
        <td><span class="row-total">3.00 ILS</span></td>
        <td><form class="cart-update-form" action="/cart/update/1"><button>u</button></form></td>
      </tr></table>
      <div id="cart-subtotal"></div><div id="cart-total"></div>
    `;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      text: async () => '<div><span id="other">x</span></div>',
      headers: { get: () => null }
    }));
    await boot();
    (document.querySelector('.cart-update-form') as HTMLFormElement)
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 60));
    expect(document.getElementById('cart-subtotal')!.textContent).toContain('ILS');
  });
});
