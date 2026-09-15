import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';

describe('static/js/i18n.js (extra)', () => {
  beforeAll(async () => {
    document.documentElement.lang = 'ar';
    await import('../../static/js/i18n.js');
  });

  afterEach(() => {
    document.documentElement.lang = 'ar';
    document.body.innerHTML = '';
    delete (window as any).Swal;
    delete (window as any).confirm;
    delete (window as any).alert;
  });

  it('falls back to Arabic when <html lang> is empty', () => {
    document.documentElement.lang = '';
    expect((window as any).t('Save')).toBe('حفظ');
    expect((window as any).t('Cancel')).toBe('إلغاء');
  });

  it('falls back to Arabic for an unsupported language', () => {
    document.documentElement.lang = 'fr';
    expect((window as any).t('Save')).toBe('حفظ');
    expect((window as any).t('Delete')).toBe('حذف');
  });

  it('runs the params loop without altering plain translations', () => {
    document.documentElement.lang = 'ar';
    expect((window as any).t('Save', { name: 'x' })).toBe('حفظ');
    expect((window as any).t('Save', { a: '1', b: '2' })).toBe('حفظ');
    document.documentElement.lang = 'en';
    expect((window as any).t('Save', { x: 'y' })).toBe('Save');
  });

  it('auto-translates [data-i18n] elements on DOMContentLoaded', () => {
    document.documentElement.lang = 'ar';
    document.body.innerHTML = '<span data-i18n="Delete"></span><span data-i18n="Cancel"></span>';
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const spans = Array.from(document.querySelectorAll('[data-i18n]'));
    expect(spans[0].textContent).toBe('حذف');
    expect(spans[1].textContent).toBe('إلغاء');
  });

  it('confirmAction fallback tolerates a missing onConfirm', () => {
    delete (window as any).Swal;
    document.documentElement.lang = 'ar';
    (window as any).confirm = () => true;
    expect(() => (window as any).confirmAction('Delete', 'Are you sure?')).not.toThrow();
    (window as any).confirm = () => false;
    expect(() => (window as any).confirmAction('Delete', 'Are you sure?')).not.toThrow();
  });

  it('showAlert defaults to the info icon', () => {
    const fire = vi.fn();
    (window as any).Swal = { fire };
    document.documentElement.lang = 'en';
    (window as any).showAlert('Save', 'Cancel');
    expect(fire).toHaveBeenCalledTimes(1);
    expect(fire).toHaveBeenCalledWith({
      title: 'Save',
      text: 'Cancel',
      icon: 'info',
      confirmButtonText: 'OK'
    });
  });

  it('getDataTablesLanguage builds the full English config', () => {
    document.documentElement.lang = 'en';
    const lang = (window as any).getDataTablesLanguage();
    expect(lang.sEmptyTable).toBe('No data available');
    expect(lang.sInfoFiltered).toContain('filtered from');
    expect(lang.sLengthMenu).toContain('Show');
    expect(lang.sLoadingRecords).toContain('Loading');
    expect(lang.sProcessing).toContain('Processing');
    expect(lang.sSearch).toBe('Search:');
    expect(lang.sZeroRecords).toBe('No records found');
    expect(lang.oPaginate.sFirst).toBe('First');
    expect(lang.oPaginate.sLast).toBe('Last');
    expect(lang.oPaginate.sNext).toBe('Next');
    expect(lang.oPaginate.sPrevious).toBe('Previous');
  });

  it('translatePage leaves unknown keys as-is', () => {
    document.documentElement.lang = 'ar';
    document.body.innerHTML = '<span data-i18n="Totally-Untranslated-Key"></span>';
    (window as any).translatePage();
    expect(document.querySelector('[data-i18n]')?.textContent).toBe('Totally-Untranslated-Key');
  });
});
