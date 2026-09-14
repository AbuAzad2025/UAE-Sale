import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

describe('static/js/i18n.js', () => {
  beforeAll(async () => {
    document.documentElement.lang = 'ar';
    await import('../../static/js/i18n.js');
  });

  afterAll(() => {
    document.documentElement.lang = '';
  });

  describe('t()', () => {
    it('installs t on window', () => {
      expect(typeof (window as any).t).toBe('function');
    });

    it('translates known keys to Arabic by default', () => {
      expect((window as any).t('Save')).toBe('حفظ');
      expect((window as any).t('Delete')).toBe('حذف');
      expect((window as any).t('Error')).toBe('خطأ');
    });

    it('translates to English when <html lang=en>', () => {
      document.documentElement.lang = 'en';
      expect((window as any).t('Save')).toBe('Save');
      expect((window as any).t('Processing')).toBe('Processing...');
      document.documentElement.lang = 'ar';
    });

    it('returns the key as-is for missing translations', () => {
      expect((window as any).t('Totally-Untranslated-Key')).toBe('Totally-Untranslated-Key');
    });

    it('handles empty params object', () => {
      expect((window as any).t('Save', {})).toBe('حفظ');
    });
  });

  describe('getDataTablesLanguage()', () => {
    it('returns Arabic.json URL for Arabic pages', () => {
      document.documentElement.lang = 'ar';
      const lang = (window as any).getDataTablesLanguage();
      expect(lang.url).toBe('/static/datatables/Arabic.json');
    });

    it('builds English strings for English pages', () => {
      document.documentElement.lang = 'en';
      const lang = (window as any).getDataTablesLanguage();
      expect(lang.sEmptyTable).toBe('No data available');
      expect(lang.sInfo).toContain('Showing');
      expect(lang.oPaginate.sNext).toBe('Next');
      document.documentElement.lang = 'ar';
    });
  });

  describe('translatePage()', () => {
    it('translates all [data-i18n] elements', () => {
      document.body.innerHTML =
        '<span data-i18n="Save"></span><span data-i18n="Cancel"></span>';
      document.documentElement.lang = 'ar';
      (window as any).translatePage();
      const spans = Array.from(document.querySelectorAll('[data-i18n]'));
      expect(spans[0].textContent).toBe('حفظ');
      expect(spans[1].textContent).toBe('إلغاء');
      document.body.innerHTML = '';
    });
  });

  describe('showAlert() / confirmAction()', () => {
    it('uses Swal with translated strings when available', () => {
      const fire = vi.fn();
      (window as any).Swal = { fire };
      document.documentElement.lang = 'ar';
      (window as any).showAlert('Save', 'Cancel', 'success');
      expect(fire).toHaveBeenCalledTimes(1);
      expect(fire).toHaveBeenCalledWith({
        title: 'حفظ',
        text: 'إلغاء',
        icon: 'success',
        confirmButtonText: 'موافق'
      });
      delete (window as any).Swal;
    });

    it('falls back to window.alert when Swal is missing', () => {
      delete (window as any).Swal;
      const alertMock = vi.fn();
      (window as any).alert = alertMock;
      document.documentElement.lang = 'ar';
      (window as any).showAlert('Save', 'Cancel');
      expect(alertMock).toHaveBeenCalledWith('حفظ\nإلغاء');
      delete (window as any).alert;
    });

    it('calls onConfirm when Swal confirms', async () => {
      (window as any).Swal = { fire: vi.fn().mockResolvedValue({ isConfirmed: true }) };
      const onConfirm = vi.fn();
      (window as any).confirmAction('Delete', 'Are you sure?', onConfirm);
      await new Promise((r) => setTimeout(r, 0));
      expect(onConfirm).toHaveBeenCalledTimes(1);
      delete (window as any).Swal;
    });

    it('skips onConfirm when Swal is dismissed', async () => {
      (window as any).Swal = { fire: vi.fn().mockResolvedValue({ isConfirmed: false }) };
      const onConfirm = vi.fn();
      (window as any).confirmAction('Delete', 'Are you sure?', onConfirm);
      await new Promise((r) => setTimeout(r, 0));
      expect(onConfirm).not.toHaveBeenCalled();
      delete (window as any).Swal;
    });

    it('falls back to window.confirm', () => {
      delete (window as any).Swal;
      const onConfirm = vi.fn();
      (window as any).confirm = () => true;
      (window as any).confirmAction('Delete', 'Are you sure?', onConfirm);
      expect(onConfirm).toHaveBeenCalledTimes(1);
      (window as any).confirm = () => false;
      (window as any).confirmAction('Delete', 'Are you sure?', onConfirm);
      expect(onConfirm).toHaveBeenCalledTimes(1);
      delete (window as any).confirm;
    });
  });
});