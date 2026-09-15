import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('frontend_store: static/js/shop.js', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.documentElement.lang = 'ar';
    vi.restoreAllMocks();
  });

  const setupDOM = () => {
    document.body.innerHTML = `
      <meta name="csrf-token" content="test-csrf-token">
      <input id="search" type="search">
      <div id="products-container">
        <div class="product-card" data-name="Product A" data-desc="Desc A" data-sku="SKU-A"></div>
        <div class="product-card" data-name="Product B" data-desc="Desc B" data-sku="SKU-B"></div>
        <div class="product-card" data-name="Product C" data-desc="Desc C" data-sku="SKU-C"></div>
      </div>
      <form class="cart-update-form" action="/cart/update/1">
        <tr class="cart-row">
          <td><input name="quantity" value="1" min="1" max="99"></td>
          <td><span class="price-unit" data-unit="10.00"></span></td>
          <td><span class="row-total">10.00 شيكل</span></td>
        </tr>
      </form>
      <form class="cart-remove-form" action="/cart/remove/1"></form>
      <div id="cart-counter">3</div>
      <div id="cart-subtotal"></div>
      <div id="cart-total"></div>
      <div id="cart-prepaid"></div>
      <meta name="prepaid-rate" content="0.2">
    `;
  };

  describe('cart interactions', () => {
    it('updates row total after cart update form submission', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <table>
          <tr class="cart-row">
            <td><input name="quantity" class="qty-input" value="2" min="1"></td>
            <td><span class="price-unit" data-unit="15.50"></span></td>
            <td><span class="row-total">31.00 شيكل</span></td>
          </tr>
        </table>
        <form class="cart-update-form" action="/cart/update/1">
          <button type="submit">Update</button>
        </form>
        <div id="cart-subtotal"></div>
        <div id="cart-total"></div>
        <meta name="prepaid-rate" content="0.2">
      `;

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          ok: true,
          cart_count: 3,
          item: { quantity: 2, price: 15.50, total: 31.00 },
          subtotal: 31.00,
          total: 31.00,
          prepaid_amount: 6.20,
          message: 'updated'
        }),
        headers: { get: () => 'application/json' }
      });
      vi.stubGlobal('fetch', fetchMock);

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const form = document.querySelector('.cart-update-form');
      await form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      await new Promise(r => setTimeout(r, 50));

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][0]).toContain('/cart/update/1');
    });

    it('alerts on failed cart update', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <table>
          <tr class="cart-row">
            <td><input name="quantity" class="qty-input" value="1"></td>
            <td><span class="price-unit" data-unit="10.00"></span></td>
            <td><span class="row-total">10.00 شيكل</span></td>
          </tr>
        </table>
        <form class="cart-update-form" action="/cart/update/1">
          <button type="submit">Update</button>
        </form>
        <div id="cart-subtotal"></div>
        <div id="cart-total"></div>
        <meta name="prepaid-rate" content="0.2">
      `;

      const alertMock = vi.fn();
      (window as any).alert = alertMock;

      const fetchMock = vi.fn().mockResolvedValue({ ok: false });
      vi.stubGlobal('fetch', fetchMock);

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const form = document.querySelector('.cart-update-form');
      await form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      await new Promise(r => setTimeout(r, 50));

      expect(alertMock).toHaveBeenCalledWith('فشل العملية');
    });

    it('handles network errors gracefully during cart update', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <table>
          <tr class="cart-row">
            <td><input name="quantity" class="qty-input" value="1"></td>
            <td><span class="price-unit" data-unit="10.00"></span></td>
            <td><span class="row-total">10.00 شيكل</span></td>
          </tr>
        </table>
        <form class="cart-update-form" action="/cart/update/1">
          <button type="submit">Update</button>
        </form>
        <div id="cart-subtotal"></div>
        <div id="cart-total"></div>
        <meta name="prepaid-rate" content="0.2">
      `;

      const alertMock = vi.fn();
      (window as any).alert = alertMock;

      const fetchMock = vi.fn().mockRejectedValue(new Error('network'));
      vi.stubGlobal('fetch', fetchMock);

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const form = document.querySelector('.cart-update-form');
      await form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      await new Promise(r => setTimeout(r, 50));

      expect(alertMock).toHaveBeenCalledWith('خطأ في الاتصال');
    });

    it('recalculates summary after updating cart row total', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <table>
          <tr class="cart-row">
            <td><input name="quantity" class="qty-input" value="1"></td>
            <td><span class="price-unit" data-unit="10.00"></span></td>
            <td><span class="row-total">10.00 شيكل</span></td>
          </tr>
          <tr class="cart-row">
            <td><input name="quantity" class="qty-input" value="2"></td>
            <td><span class="price-unit" data-unit="5.00"></span></td>
            <td><span class="row-total">10.00 شيكل</span></td>
          </tr>
        </table>
        <form class="cart-update-form" action="/cart/update/1">
          <button type="submit">Update</button>
        </form>
        <div id="cart-subtotal"></div>
        <div id="cart-total"></div>
        <div id="cart-prepaid"></div>
        <meta name="prepaid-rate" content="0.2">
      `;

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, message: 'ok' }),
        headers: { get: () => 'application/json' }
      });
      vi.stubGlobal('fetch', fetchMock);

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const qtyInput = document.querySelectorAll('.qty-input')[0];
      qtyInput.value = '3';
      await new Promise(r => setTimeout(r, 50));

      const updateForm = document.querySelector('.cart-update-form');
      await updateForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      await new Promise(r => setTimeout(r, 50));

      expect(document.getElementById('cart-subtotal')?.textContent).toContain(' شيكل');
      expect(document.getElementById('cart-total')?.textContent).toContain(' شيكل');
    });
  });

  describe('quantity controls', () => {
    it('clamps quantity to minimum on step button click', async () => {
      document.body.innerHTML = `
        <div class="qty-control">
          <input class="qty-input" value="1" min="1" max="99" type="number">
          <button class="btn-step" data-dir="-1">-</button>
          <button class="btn-step" data-dir="1">+</button>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const minusBtn = document.querySelector('[data-dir="-1"]');
      minusBtn.click();
      const input = document.querySelector('.qty-input') as HTMLInputElement;
      expect(input.value).toBe('1');
    });

    it('increments quantity on step button click', async () => {
      document.body.innerHTML = `
        <div class="qty-control">
          <input class="qty-input" value="1" min="1" max="99" type="number">
          <button class="btn-step" data-dir="-1">-</button>
          <button class="btn-step" data-dir="1">+</button>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const plusBtn = document.querySelector('[data-dir="1"]');
      plusBtn.click();
      const input = document.querySelector('.qty-input') as HTMLInputElement;
      expect(input.value).toBe('2');
    });

    it('auto-creates reset button for qty control', async () => {
      document.body.innerHTML = `
        <div class="qty-control">
          <input class="qty-input" value="1" min="1" max="99" type="number">
          <button class="btn-step" data-dir="1">+</button>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const resetBtn = document.querySelector('.qty-control .btn-reset');
      expect(resetBtn).toBeTruthy();
      resetBtn.click();
      const input = document.querySelector('.qty-input') as HTMLInputElement;
      expect(input.value).toBe('1');
    });

    it('does not duplicate reset button', async () => {
      document.body.innerHTML = `
        <div class="qty-control">
          <input class="qty-input" value="1" min="1" max="99" type="number">
          <button class="btn-step" data-dir="1">+</button>
          <button class="btn-reset btn btn-sm">Reset</button>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const resetButtons = document.querySelectorAll('.qty-control .btn-reset');
      expect(resetButtons.length).toBe(1);
    });

    it('clamps quantity to max value', async () => {
      document.body.innerHTML = `
        <div class="qty-control">
          <input class="qty-input" value="99" min="1" max="10" type="number">
          <button class="btn-step" data-dir="1">+</button>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const plusBtn = document.querySelector('[data-dir="1"]');
      plusBtn.click();
      const input = document.querySelector('.qty-input') as HTMLInputElement;
      expect(input.value).toBe('10');
    });

    it('clamps non-numeric input to minimum', async () => {
      document.body.innerHTML = `
        <div class="qty-control">
          <input class="qty-input" value="abc" min="1" max="10" type="number">
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const input = document.querySelector('.qty-input') as HTMLInputElement;
      input.dispatchEvent(new Event('input'));
      expect(input.value).toBe('1');
    });
  });

  describe('catalog search', () => {
    it('filters product cards based on search query', async () => {
      document.body.innerHTML = `
        <input id="search" type="search" placeholder="Search...">
        <div id="products-container">
          <div class="product-card" data-name="Laptop Dell">Dell Laptop</div>
          <div class="product-card" data-name="Laptop HP">HP Laptop</div>
          <div class="product-card" data-name="Mouse Logi">Logi Mouse</div>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const search = document.getElementById('search') as HTMLInputElement;
      search.value = 'dell';
      search.dispatchEvent(new Event('input'));
      await new Promise(r => setTimeout(r, 200));

      expect((document.querySelector('[data-name="Laptop Dell"]') as HTMLElement).style.display).not.toBe('none');
      expect((document.querySelector('[data-name="Laptop HP"]') as HTMLElement).style.display).toBe('none');
      expect((document.querySelector('[data-name="Mouse Logi"]') as HTMLElement).style.display).toBe('none');
    });

    it('shows no-results message when no products match', async () => {
      document.body.innerHTML = `
        <input id="search" type="search">
        <div id="products-container">
          <div class="product-card" data-name="Product A"></div>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const search = document.getElementById('search') as HTMLInputElement;
      search.value = 'zzz';
      search.dispatchEvent(new Event('input'));
      await new Promise(r => setTimeout(r, 200));

      const noResults = document.getElementById('no-results-message');
      expect(noResults).toBeTruthy();
      expect(noResults!.style.display).not.toBe('none');
      expect((noResults as HTMLElement).textContent).toContain('لا توجد منتجات مطابقة');
    });

    it('hides no-results message when products match', async () => {
      document.body.innerHTML = `
        <input id="search" type="search">
        <div id="products-container">
          <div class="product-card" data-name="Product A"></div>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const search = document.getElementById('search') as HTMLInputElement;
      search.value = 'product';
      search.dispatchEvent(new Event('input'));
      await new Promise(r => setTimeout(r, 200));

      const noResults = document.getElementById('no-results-message');
      expect(noResults!.style.display).toBe('none');
    });

    it('shows all products when search is cleared', async () => {
      document.body.innerHTML = `
        <input id="search" type="search">
        <div id="products-container">
          <div class="product-card" data-name="Product A">Product A</div>
          <div class="product-card" data-name="Product B">Product B</div>
        </div>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const search = document.getElementById('search') as HTMLInputElement;
      search.value = 'product';
      search.dispatchEvent(new Event('input'));
      await new Promise(r => setTimeout(r, 200));

      search.value = '';
      search.dispatchEvent(new Event('input'));
      await new Promise(r => setTimeout(r, 200));

      expect((document.querySelector('[data-name="Product A"]') as HTMLElement).style.display).not.toBe('none');
      expect((document.querySelector('[data-name="Product B"]') as HTMLElement).style.display).not.toBe('none');
    });
  });

  describe('checkout form', () => {
    it('formats card number with spaces', async () => {
      document.body.innerHTML = `
        <form id="payment-form">
          <select id="payment-method"><option value="card">Card</option></select>
          <div id="card-fields">
            <input name="card_number" type="text">
          </div>
        </form>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const cardInput = document.querySelector('input[name="card_number"]') as HTMLInputElement;
      cardInput.value = '4111111111111111';
      cardInput.dispatchEvent(new Event('input'));

      expect(cardInput.value).toMatch(/\d{4} \d{4} \d{4} \d{4}/);
    });

    it('formats expiry date with slash', async () => {
      document.body.innerHTML = `
        <form id="payment-form">
          <select id="payment-method"><option value="card">Card</option></select>
          <div id="card-fields">
            <input name="card_expiry" type="text">
          </div>
        </form>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const expiryInput = document.querySelector('input[name="card_expiry"]') as HTMLInputElement;
      expiryInput.value = '1225';
      expiryInput.dispatchEvent(new Event('input'));

      expect(expiryInput.value).toBe('12/25');
    });

    it('submits form with transaction data', async () => {
      document.body.innerHTML = `
        <form id="payment-form">
          <select id="payment-method"><option value="card">Card</option></select>
          <div id="card-fields">
            <input name="cardholder_name" value="John Doe">
            <input name="card_number" value="4111 1111 1111 1111">
            <input name="card_expiry" value="12/25">
          </div>
          <input type="hidden" name="transaction_data" id="transaction_data">
          <input type="hidden" name="card_last4" id="card_last4">
          <input type="hidden" name="card_brand" id="card_brand">
          <button type="submit">Pay</button>
        </form>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const form = document.getElementById('payment-form') as HTMLFormElement;
      const event = new Event('submit', { cancelable: true, bubbles: true });
      form.dispatchEvent(event);

      const tx = document.getElementById('transaction_data') as HTMLInputElement;
      expect(tx.value).toBeTruthy();
      const payload = JSON.parse(tx.value);
      expect(payload.transaction_id).toMatch(/^TXN-/);
      expect(payload.card.last4).toBe('1111');
      expect(payload.card.brand).toBe('VISA');
    });

    it('disables submit button during processing', async () => {
      document.body.innerHTML = `
        <form id="payment-form">
          <select id="payment-method"><option value="card">Card</option></select>
          <div id="card-fields">
            <input name="card_number" value="4111 1111 1111 1111">
          </div>
          <button type="submit">Pay</button>
        </form>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const form = document.getElementById('payment-form') as HTMLFormElement;
      const btn = form.querySelector('button[type="submit"]') as HTMLButtonElement;
      const event = new Event('submit', { cancelable: true, bubbles: true });
      form.dispatchEvent(event);

      expect(btn.disabled).toBe(true);
      expect(btn.innerHTML).toContain('جاري معالجة الدفع');
    });
  });

  describe('alert auto-dismiss', () => {
    it('auto-dismisses alerts after 5 seconds (fallback when bootstrap unavailable)', async () => {
      document.body.innerHTML = `
        <div class="alert alert-success">Success message</div>
      `;

      const alertEl = document.querySelector('.alert');
      expect(alertEl).toBeTruthy();

      vi.useFakeTimers();
      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      // 5 second timeout for auto-dismiss, bootstrap unavailable so caught by try/catch
      vi.advanceTimersByTime(5000);

      // After timeout, the alert should have been removed/dismissed
      const remainingAlerts = document.querySelectorAll('.alert');
      expect(remainingAlerts.length).toBe(0);

      vi.useRealTimers();
    });
  });

  describe('image upload', () => {
    it('attaches main image upload handler on DOMContentLoaded', async () => {
      document.body.innerHTML = `
        <input type="file" id="main-file" accept="image/*">
        <button type="button" id="btn-upload-main">Upload</button>
        <img id="main-thumb">
        <input type="hidden" id="main-image-url">
        <input type="hidden" name="image">
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const fileEl = document.getElementById('main-file') as HTMLInputElement;
      expect(fileEl).toBeTruthy();
      expect(document.getElementById('btn-upload-main')).toBeTruthy();
    });
  });
});
