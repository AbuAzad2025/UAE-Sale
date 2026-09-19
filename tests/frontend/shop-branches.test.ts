import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

describe('shop uncovered branches', () => {
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

  it('catalog search normalizes Persian digits', async () => {
    document.body.innerHTML = `
      <input id="search" type="search">
      <div id="products-container">
        <div class="product-card" data-name="قلم" data-sku="SKU-456"><span class="card-title">Pen</span></div>
        <div class="product-card" data-name="دفتر"><span class="card-title">Notebook</span></div>
      </div>
    `;
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const search = document.getElementById('search') as HTMLInputElement;
    search.value = '۴۵۶';
    search.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 250));
    const cards = document.querySelectorAll('.product-card') as NodeListOf<HTMLElement>;
    expect(cards[0].style.display).not.toBe('none');
    expect(cards[1].style.display).toBe('none');
  });

  it('quick-category success without modal element covers missing-el branch', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <form id="quick-category-form" data-url="/api/cat" action="/api/cat">
        <input id="qc-name" value="NewCat">
      </form>
      <select name="category_id" id="category_id"></select>
    `;
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, id: 11, name: 'NewCat' })
    });
    vi.stubGlobal('fetch', fetchMock);
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const form = document.getElementById('quick-category-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 50));
    const sel = document.getElementById('category_id') as HTMLSelectElement;
    expect(sel.options.length).toBe(1);
    expect(sel.options[0].value).toBe('11');
  });

  it('hideBsModal jQuery path cleans up after timeout', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <form id="quick-category-form" data-url="/api/cat" action="/api/cat">
        <input id="qc-name" value="C2">
      </form>
      <select name="category_id" id="category_id"></select>
      <div id="quickCategoryModal" class="show"></div>
      <div class="modal-backdrop"></div>
    `;
    document.body.classList.add('modal-open');
    const modalMock = { hide: vi.fn() };
    (window as any).jQuery = Object.assign(vi.fn(() => ({ modal: vi.fn() })), {
      fn: { modal: true }
    });
    void modalMock;
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, id: 12, name: 'C2' })
    });
    vi.stubGlobal('fetch', fetchMock);
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const form = document.getElementById('quick-category-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 300));
    expect(document.querySelector('.modal-backdrop')).toBeNull();
    expect(document.body.classList.contains('modal-open')).toBe(false);
  });

  it('loadOnlineData network failure sets error status', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="21" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-warehouse-badge" class="bg-secondary"></span>
        <form id="online-form"><input id="online-price"><input id="online-qty"><span id="online-image-url"></span><img id="online-thumb"><span id="online-status"></span></form>
        <input type="file" id="online-file"><button id="btn-upload-online"></button><button id="btn-save-online"></button>
      </div>
    `;
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 4, name: 'W4' }] }) });
      }
      return Promise.reject(new Error('net down'));
    });
    vi.stubGlobal('fetch', fetchMock);
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    expect((document.getElementById('online-status') as HTMLElement).textContent).toBe('تعذر تحميل البيانات.');
  });

  it('uploadOnlineImage failure response and network error paths', async () => {
    const panel = (pid: string) => `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="${pid}" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-warehouse-badge"></span>
        <form id="online-form"><input id="online-price"><input id="online-qty"><span id="online-image-url"></span><img id="online-thumb"><span id="online-status"></span></form>
        <input type="file" id="online-file"><button id="btn-upload-online"></button><button id="btn-save-online"></button>
      </div>
    `;
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    // failure response (!ok)
    document.body.innerHTML = panel('22');
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 1, name: 'W' }] }) });
      }
      if (String(url).includes('/api/prod/')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
      }
      return Promise.resolve({ ok: false, json: async () => ({ ok: false, error: 'فشل الرفع' }) });
    }));
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    const fileEl = document.getElementById('online-file') as HTMLInputElement;
    Object.defineProperty(fileEl, 'files', { value: [new File(['x'], 'a.png')], configurable: true });
    fileEl.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('فشل الرفع');
    expect((document.getElementById('online-status') as HTMLElement).textContent).toBe('فشل الرفع');

    // network throw
    document.body.innerHTML = panel('23');
    delete (document.body.dataset as any).cartWired;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 1, name: 'W' }] }) });
      }
      if (String(url).includes('/api/prod/')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
      }
      return Promise.reject(new Error('net'));
    }));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    const fileEl2 = document.getElementById('online-file') as HTMLInputElement;
    Object.defineProperty(fileEl2, 'files', { value: [new File(['x'], 'b.png')], configurable: true });
    fileEl2.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 50));
    expect((document.getElementById('online-status') as HTMLElement).textContent).toBe('تعذر رفع الصورة');
  });

  it('saveOnline failure response and network error paths', async () => {
    const panel = (pid: string) => `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="${pid}" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-status"></span>
        <input id="online-price" value="10"><input id="online-qty" value="2"><span id="online-image-url"></span>
        <button id="btn-save-online"></button>
      </div>
    `;
    const alertMock = vi.fn();
    (window as any).alert = alertMock;
    // !ok response
    document.body.innerHTML = panel('24');
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 6, name: 'W6' }] }) });
      }
      if (String(url).includes('/api/prod/')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
      }
      return Promise.resolve({ ok: false, json: async () => ({ ok: false, error: 'تعذر الحفظ' }) });
    }));
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    (document.getElementById('btn-save-online') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect(alertMock).toHaveBeenCalledWith('تعذر الحفظ');
    expect((document.getElementById('online-status') as HTMLElement).textContent).toBe('تعذر الحفظ');

    // network throw
    document.body.innerHTML = panel('25');
    delete (document.body.dataset as any).cartWired;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 6, name: 'W6' }] }) });
      }
      if (String(url).includes('/api/prod/')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
      }
      return Promise.reject(new Error('net'));
    }));
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    (document.getElementById('btn-save-online') as HTMLButtonElement).click();
    await new Promise(r => setTimeout(r, 50));
    expect((document.getElementById('online-status') as HTMLElement).textContent).toBe('تعذر الحفظ');
  });

  it('applyCartJSON covers item quantity/price/total branches when form is inside row', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table>
        <tr class="cart-row" id="row1">
          <td><input name="quantity" value="1"></td>
          <td><span class="price-unit" data-unit="10.00">10.00</span></td>
          <td><span class="row-total">10.00 ILS</span></td>
          <td><form class="cart-update-form" action="/cart/update/1"><button>u</button></form></td>
        </tr>
        <tr class="cart-row" id="row2">
          <td><input name="quantity" value="2"></td>
          <td><span class="price-unit">5.00 ILS</span></td>
          <td><span class="row-total">10.00 ILS</span></td>
        </tr>
      </table>
      <div id="cart-counter">0</div><div id="cart-subtotal"></div><div id="cart-total"></div><div id="cart-prepaid"></div>
      <meta name="prepaid-rate" content="0.2">
    `;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, cart_count: 3, item: { quantity: 4, price: '20.00', total: 80 } }),
      headers: { get: () => 'application/json' }
    }));
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const form = document.querySelector('.cart-update-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 80));
    const row = document.getElementById('row1') as HTMLElement;
    expect((row.querySelector('input[name="quantity"]') as HTMLInputElement).value).toBe('4');
    expect((row.querySelector('.price-unit') as HTMLElement).getAttribute('data-unit')).toBe('20.00');
    expect((row.querySelector('.row-total') as HTMLElement).textContent).toContain('ILS');
    expect(document.getElementById('cart-counter')!.textContent).toBe('3');
  });

  it('recalcRowTotal fallbacks when price-unit and row-total are missing', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table>
        <tr class="cart-row" id="bare">
          <td><form class="cart-update-form" action="/cart/update/9"><button>u</button></form></td>
        </tr>
        <tr class="cart-row" id="other">
          <td><input name="quantity" value="2"></td>
          <td><span class="price-unit" data-unit="5.00"></span></td>
          <td><span class="row-total">10.00 ILS</span></td>
        </tr>
      </table>
      <div id="cart-subtotal"></div><div id="cart-total"></div>
    `;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
      headers: { get: () => 'application/json' }
    }));
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const form = document.querySelector('.cart-update-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 80));
    expect(document.getElementById('cart-subtotal')!.textContent).toContain('ILS');
  });

  it('cart remove form removes its row and recalcs', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <table>
        <tr class="cart-row" id="r1">
          <td><span class="row-total">10.00 ILS</span></td>
          <td><form class="cart-remove-form" action="/cart/remove/1"><button>r</button></form></td>
        </tr>
        <tr class="cart-row" id="r2"><td><span class="row-total">5.00 ILS</span></td></tr>
      </table>
      <div id="cart-subtotal"></div><div id="cart-total"></div>
    `;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
      headers: { get: () => 'application/json' }
    }));
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const form = document.querySelector('.cart-remove-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 80));
    expect(document.getElementById('r1')).toBeNull();
    expect(document.getElementById('cart-subtotal')!.textContent).toContain('5.00');
  });

  it('online image field highlight resets after timeout', async () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="t">
      <div id="online-panel" data-pid="26" data-list-url="/api/list" data-products-url-template="/api/prod/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/upd/PLACEHOLDER1/PLACEHOLDER2">
        <span id="online-status"></span>
        <form id="online-form"><input id="online-price"><input id="online-qty"><span id="online-image-url"></span><img id="online-thumb"></form>
        <input type="file" id="online-file"><button id="btn-upload-online"></button><button id="btn-save-online"></button>
      </div>
      <input name="online_image">
    `;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/list')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [{ id: 1, name: 'W' }] }) });
      }
      if (String(url).includes('/api/prod/')) {
        return Promise.resolve({ ok: true, json: async () => ({ data: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ ok: true, url: 'http://u', thumb_url: 'http://t' }) });
    }));
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 80));
    const fileEl = document.getElementById('online-file') as HTMLInputElement;
    Object.defineProperty(fileEl, 'files', { value: [new File(['x'], 'c.png')], configurable: true });
    fileEl.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 50));
    const field = document.querySelector('input[name="online_image"]') as HTMLInputElement;
    expect(field.value).toBe('http://u');
    await new Promise(r => setTimeout(r, 2100));
    expect(field.style.backgroundColor).toBe('');
  });

  it('main image field highlight resets after timeout', async () => {
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
      json: async () => ({ ok: true, url: 'http://main', thumb_url: 'http://main-t' })
    }));
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const fileEl = document.getElementById('main-file') as HTMLInputElement;
    Object.defineProperty(fileEl, 'files', { value: [new File(['x'], 'm.png')], configurable: true });
    fileEl.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 80));
    const field = document.querySelector('input[name="image"]') as HTMLInputElement;
    expect(field.value).toBe('http://main');
    await new Promise(r => setTimeout(r, 2100));
    expect(field.style.backgroundColor).toBe('');
  });

  it('alert auto-dismiss uses bootstrap Alert when available', async () => {
    vi.useFakeTimers();
    const closeMock = vi.fn();
    (window as any).bootstrap = { Alert: function () { return { close: closeMock }; } };
    document.body.innerHTML = `<div class="alert">hi</div>`;
    await import('../../static/js/shop.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await vi.advanceTimersByTimeAsync(5100);
    expect(closeMock).toHaveBeenCalled();
  });
});
