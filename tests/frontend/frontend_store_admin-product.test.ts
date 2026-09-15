import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('frontend_store: shop admin product form', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.documentElement.lang = 'ar';
  });

  describe('toggle active badge text', () => {
    it('shows active text after activating an inactive product', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <span id="prod-status-badge" class="badge badge-inactive">غير مفعل</span>
        <button id="toggle-active-btn" data-toggle-url="/api/products/1/toggle"></button>
      `;

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, message: 'تم التحديث' })
      });
      vi.stubGlobal('fetch', fetchMock);
      const alertMock = vi.fn();
      (window as any).alert = alertMock;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const toggleBtn = document.getElementById('toggle-active-btn') as HTMLButtonElement;
      toggleBtn.click();
      await new Promise(r => setTimeout(r, 50));

      const badge = document.getElementById('prod-status-badge') as HTMLElement;
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(badge.classList.contains('badge-active')).toBe(true);
      expect(badge.classList.contains('badge-inactive')).toBe(false);
      expect(badge.textContent).toBe('مفعَل');
      expect(alertMock).toHaveBeenCalledWith('تم التحديث');
    });

    it('shows inactive text after deactivating an active product', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <span id="prod-status-badge" class="badge badge-active">مفعَل</span>
        <button id="toggle-active-btn" data-toggle-url="/api/products/1/toggle"></button>
      `;

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, message: 'تم التحديث' })
      });
      vi.stubGlobal('fetch', fetchMock);
      const alertMock = vi.fn();
      (window as any).alert = alertMock;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const toggleBtn = document.getElementById('toggle-active-btn') as HTMLButtonElement;
      toggleBtn.click();
      await new Promise(r => setTimeout(r, 50));

      const badge = document.getElementById('prod-status-badge') as HTMLElement;
      expect(badge.classList.contains('badge-inactive')).toBe(true);
      expect(badge.classList.contains('badge-active')).toBe(false);
      expect(badge.textContent).toBe('غير مفعَل');
    });

    it('handles toggle failure gracefully', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <span id="prod-status-badge" class="badge badge-active">مفعَل</span>
        <button id="toggle-active-btn" data-toggle-url="/api/products/1/toggle"></button>
      `;

      const fetchMock = vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ message: 'تعذر التحديث' })
      });
      vi.stubGlobal('fetch', fetchMock);
      const alertMock = vi.fn();
      (window as any).alert = alertMock;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const toggleBtn = document.getElementById('toggle-active-btn') as HTMLButtonElement;
      toggleBtn.click();
      await new Promise(r => setTimeout(r, 50));

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(alertMock).toHaveBeenCalledWith('تعذر التحديث');
    });

    it('handles toggle network errors gracefully', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <span id="prod-status-badge" class="badge badge-active">مفعَل</span>
        <button id="toggle-active-btn" data-toggle-url="/api/products/1/toggle"></button>
      `;

      const fetchMock = vi.fn().mockRejectedValue(new Error('network'));
      vi.stubGlobal('fetch', fetchMock);
      const alertMock = vi.fn();
      (window as any).alert = alertMock;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const toggleBtn = document.getElementById('toggle-active-btn') as HTMLButtonElement;
      toggleBtn.click();
      await new Promise(r => setTimeout(r, 50));

      expect(alertMock).toHaveBeenCalledWith('تعذر الاتصال');
    });
  });

  describe('price input sanitization', () => {
    it('removes non-numeric characters from price on input', async () => {
      document.body.innerHTML = `
        <form id="product-form">
          <input name="price" id="price" value="">
        </form>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const priceInput = document.querySelector('input[name="price"]') as HTMLInputElement;
      priceInput.value = 'abc123.45xyz';
      priceInput.dispatchEvent(new Event('input'));
      expect(priceInput.value).toBe('123.45');
    });

    it('normalizes decimal separators on form submit', async () => {
      document.body.innerHTML = `
        <form id="product-form">
          <input name="price" id="price" value="1.234,56">
        </form>
      `;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const priceInput = document.querySelector('input[name="price"]') as HTMLInputElement;
      priceInput.value = '1.234,56';
      const submitEvent = new Event('submit', { cancelable: true, bubbles: true });
      const form = document.getElementById('product-form') as HTMLFormElement;
      form.dispatchEvent(submitEvent);

      expect(priceInput.value).toBe('1234.56');
    });
  });

  describe('quick update button', () => {
    it('sends update request with name and price', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <form id="product-form">
          <input name="name" id="name" value="">
          <input name="price" id="price" value="">
        </form>
        <input id="quick-name" value="New Product">
        <input id="quick-price" value="99.99">
        <button id="quick-update-btn" data-update-url="/api/products/1">Update</button>
        <input type="hidden" id="transaction_data">
        <input type="hidden" id="card_last4">
        <input type="hidden" id="card_brand">
      `;

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, message: 'تم التحديث' })
      });
      vi.stubGlobal('fetch', fetchMock);
      const alertMock = vi.fn();
      (window as any).alert = alertMock;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const btn = document.getElementById('quick-update-btn') as HTMLButtonElement;
      btn.click();
      await new Promise(r => setTimeout(r, 50));

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][0]).toContain('/api/products/1');
      expect(fetchMock.mock.calls[0][1].body).toContain('"name":"New Product"');
      expect(fetchMock.mock.calls[0][1].body).toContain('"price":"99.99"');
      expect(alertMock).toHaveBeenCalledWith('تم التحديث');
    });

    it('handles quick update failure', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <form id="product-form">
          <input name="name" id="name" value="">
          <input name="price" id="price" value="">
        </form>
        <input id="quick-name" value="New Product">
        <input id="quick-price" value="99.99">
        <button id="quick-update-btn" data-update-url="/api/products/1">Update</button>
      `;

      const fetchMock = vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ message: 'تعذر التحديث' })
      });
      vi.stubGlobal('fetch', fetchMock);
      const alertMock = vi.fn();
      (window as any).alert = alertMock;

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const btn = document.getElementById('quick-update-btn') as HTMLButtonElement;
      btn.click();
      await new Promise(r => setTimeout(r, 50));

      expect(alertMock).toHaveBeenCalledWith('تعذر التحديث');
    });

    it('skips update when no URL is provided', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <form id="product-form">
          <input name="name" id="name" value="">
          <input name="price" id="price" value="">
        </form>
        <input id="quick-name" value="New Product">
        <input id="quick-price" value="99.99">
        <button id="quick-update-btn">Update</button>
      `;

      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const btn = document.getElementById('quick-update-btn') as HTMLButtonElement;
      btn.click();
      await new Promise(r => setTimeout(r, 50));

      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  describe('online panel loading states', () => {
    it('shows loading spinner while fetching online data', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <div id="online-panel" data-pid="1" data-list-url="/api/warehouses/online" data-products-url-template="/api/products/online/PLACEHOLDER" data-upload-url="/api/upload" data-update-inline-url-template="/api/products/online/PLACEHOLDER1/PLACEHOLDER2">
          <span id="online-status"></span>
          <form id="online-form">
            <input id="online-price" value="">
            <input id="online-qty" value="">
            <input id="online-image-url" value="">
          </form>
        </div>
        <input type="file" id="online-file">
        <button id="btn-upload-online">Upload</button>
        <button id="btn-save-online">Save</button>
      `;

      const resolvers: Array<(v: any) => void> = [];
      const fetchMock = vi.fn().mockImplementation(
        () => new Promise(resolve => resolvers.push(resolve))
      );
      vi.stubGlobal('fetch', fetchMock);

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      // First fetch: warehouse list -> triggers loadOnlineData -> spinner + second fetch
      await new Promise(r => setTimeout(r, 20));
      expect(fetchMock).toHaveBeenCalledTimes(1);
      resolvers[0]({
        ok: true,
        json: async () => ({ data: [{ id: 1, name: 'Online', online_is_default: true }] })
      });
      await new Promise(r => setTimeout(r, 20));

      const statusEl = document.getElementById('online-status') as HTMLElement;
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(statusEl.innerHTML).toContain('جاري تحميل');
      expect(statusEl.innerHTML).toContain('spin');
    });
  });

  describe('cart remove form', () => {
    it('removes cart row on successful removal', async () => {
      document.body.innerHTML = `
        <meta name="csrf-token" content="test-csrf-token">
        <table>
          <tr class="cart-row" id="row-1">
            <td><input name="quantity" value="1"></td>
            <td><span class="price-unit" data-unit="10.00"></span></td>
            <td><span class="row-total">10.00 شيكل</span></td>
            <td>
              <form class="cart-remove-form" action="/cart/remove/1">
                <button type="submit">Remove</button>
              </form>
            </td>
          </tr>
          <tr class="cart-row" id="row-2">
            <td><input name="quantity" value="2"></td>
            <td><span class="price-unit" data-unit="5.00"></span></td>
            <td><span class="row-total">10.00 شيكل</span></td>
          </tr>
        </table>
        <div id="cart-subtotal"></div>
        <div id="cart-total"></div>
        <meta name="prepaid-rate" content="0.2">
      `;

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, cart_count: 0 }),
        headers: { get: () => 'application/json' }
      });
      vi.stubGlobal('fetch', fetchMock);

      await import('../../static/js/shop.js');
      document.dispatchEvent(new Event('DOMContentLoaded'));

      const form = document.querySelector('.cart-remove-form') as HTMLFormElement;
      await form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      await new Promise(r => setTimeout(r, 50));

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(document.getElementById('row-1')).toBeNull();
      expect(document.getElementById('row-2')).not.toBeNull();
      expect(document.querySelectorAll('.cart-row').length).toBe(1);
    });
  });
});
