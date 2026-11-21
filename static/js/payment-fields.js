/**
 *  Payment Fields Manager - Dynamic Payment Method Fields
 * إدارة ديناميكية لحقول طرق الدفع في كل الوحدات
 */

(function($) {
  'use strict';

  // Unified lookups (window.SYSTEM_LOOKUPS rendered by base.html from
  // LookupService); inline defaults keep the module working standalone.
  function lookupOptions(key, fallback, blankLabel) {
    let opts;
    try {
      const rows = (window.SYSTEM_LOOKUPS || {})[key];
      if (Array.isArray(rows) && rows.length) {
        opts = rows.map(function (row) {
          return { value: row[0], label: (row[1] && row[1].ar) || row[0] };
        });
      }
    } catch (e) { /* fall through to defaults */ }
    if (!opts) { opts = fallback; }
    if (blankLabel) { opts = [{ value: '', label: blankLabel }].concat(opts); }
    return opts;
  }
  
  // =====================================
  // تعريف حقول كل طريقة دفع
  // =====================================
  const PAYMENT_METHODS = {
    cash: {
      title_ar: t('Cash Payment'),
      title_en: 'Cash Payment',
      icon: 'fas fa-money-bill-wave',
      color: 'success',
      fields: []
    },
    
    card: {
      title_ar: t('Card Payment'),
      title_en: 'Card Payment',
      icon: 'fas fa-credit-card',
      color: 'primary',
      fields: [
        {
          name: 'card_last4',
          type: 'text',
          label_ar: t('Card Last 4 Digits'),
          label_en: 'Card Last 4 Digits',
          required: false,
          maxlength: 4,
          pattern: '[0-9]{4}',
          placeholder: '1234'
        },
        {
          name: 'card_type',
          type: 'select',
          label_ar: t('Card Type'),
          label_en: 'Card Type',
          required: false,
          options: lookupOptions('card_types', [
            { value: 'visa', label: 'Visa' },
            { value: 'mastercard', label: 'Mastercard' },
            { value: 'amex', label: 'American Express' },
            { value: 'other', label: t('Other') }
          ], t('Select...'))
        },
        {
          name: 'reference_number',
          type: 'text',
          label_ar: t('Transaction Number'),
          label_en: 'Transaction Number',
          required: false,
          placeholder: 'REF-123456'
        }
      ]
    },
    
    bank_transfer: {
      title_ar: t('Bank Transfer'),
      title_en: 'Bank Transfer',
      icon: 'fas fa-university',
      color: 'info',
      fields: [
        {
          name: 'reference_number',
          type: 'text',
          label_ar: t('Transfer Reference'),
          label_en: 'Transfer Reference',
          required: true,
          placeholder: 'TRF-123456'
        },
        {
          name: 'bank_name',
          type: 'text',
          label_ar: t('Bank Name'),
          label_en: 'Bank Name',
          required: false,
          placeholder: 'Emirates NBD'
        },
        {
          name: 'transfer_date',
          type: 'date',
          label_ar: t('Transfer Date'),
          label_en: 'Transfer Date',
          required: false
        }
      ]
    },
    
    cheque: {
      title_ar: t('Cheque Payment'),
      title_en: 'Cheque Payment',
      icon: 'fas fa-file-invoice',
      color: 'warning',
      fields: [
        {
          name: 'cheque_number',
          type: 'text',
          label_ar: t('Cheque Number'),
          label_en: 'Cheque Number',
          required: true,
          placeholder: 'CHQ-123456'
        },
        {
          name: 'cheque_date',
          type: 'date',
          label_ar: t('Due Date'),
          label_en: 'Due Date',
          required: true
        },
        {
          name: 'bank_name',
          type: 'text',
          label_ar: t('Bank Name'),
          label_en: 'Bank Name',
          required: true,
          placeholder: 'Emirates NBD'
        },
        {
          name: 'cheque_status',
          type: 'select',
          label_ar: t('Cheque Status'),
          label_en: 'Cheque Status',
          required: false,
          options: lookupOptions('cheque_statuses', [
            { value: 'pending', label: t('Pending') },
            { value: 'cleared', label: t('Cleared') },
            { value: 'bounced', label: t('Bounced') }
          ])
        }
      ]
    },
    
    e_wallet: {
      title_ar: t('E-Wallet'),
      title_en: 'E-Wallet',
      icon: 'fas fa-wallet',
      color: 'purple',
      fields: [
        {
          name: 'wallet_provider',
          type: 'select',
          label_ar: t('Wallet Provider'),
          label_en: 'Wallet Provider',
          required: true,
          options: lookupOptions('ewallets', [
            { value: 'apple_pay', label: 'Apple Pay' },
            { value: 'google_pay', label: 'Google Pay' },
            { value: 'samsung_pay', label: 'Samsung Pay' },
            { value: 'paypal', label: 'PayPal' },
            { value: 'other', label: t('Other') }
          ], t('Select...'))
        },
        {
          name: 'reference_number',
          type: 'text',
          label_ar: t('Transaction ID'),
          label_en: 'Transaction ID',
          required: true,
          placeholder: 'TXN-123456'
        },
        {
          name: 'wallet_phone',
          type: 'text',
          label_ar: t('Wallet Phone'),
          label_en: 'Wallet Phone',
          required: false,
          placeholder: '+971-xxx-xxx-xxx'
        }
      ]
    },
    
    credit: {
      title_ar: t('Credit'),
      title_en: 'Credit',
      icon: 'fas fa-calendar-check',
      color: 'danger',
      fields: [
        {
          name: 'credit_days',
          type: 'number',
          label_ar: t('Credit Days'),
          label_en: 'Credit Days',
          required: false,
          min: 1,
          value: 30
        },
        {
          name: 'due_date',
          type: 'date',
          label_ar: t('Due Date'),
          label_en: 'Due Date',
          required: false
        }
      ]
    }
  };
  
  // =====================================
  // إنشاء حقول ديناميكية
  // =====================================
  function renderPaymentFields(method, containerSelector, fieldPrefix = '') {
    const $container = $(containerSelector);
    $container.empty();
    
    if (!method || method === '' || !PAYMENT_METHODS[method]) {
      return;
    }
    
    const methodConfig = PAYMENT_METHODS[method];
    const fields = methodConfig.fields;
    
    if (fields.length === 0) {
      $container.html(`
        <div class="alert alert-success">
          <i class="${methodConfig.icon} mr-2"></i>
          <strong>${methodConfig.title_ar}</strong> - ${t('No additional fields required')}
        </div>
      `);
      return;
    }
    
    let html = `
      <div class="card border-${methodConfig.color} mb-3">
        <div class="card-header bg-${methodConfig.color} text-white">
          <i class="${methodConfig.icon} mr-2"></i>
          <strong>${methodConfig.title_ar}</strong>
        </div>
        <div class="card-body">
          <div class="row">
    `;
    
    fields.forEach(field => {
      const fieldName = fieldPrefix ? `${fieldPrefix}_${field.name}` : field.name;
      const requiredAttr = field.required ? 'required' : '';
      const requiredLabel = field.required ? '<span class="text-danger">*</span>' : '';
      
      html += '<div class="col-md-6"><div class="form-group">';
      html += `<label>${field.label_ar} ${requiredLabel}</label>`;
      
      if (field.type === 'select') {
        html += `<select name="${fieldName}" class="form-control" ${requiredAttr}>`;
        field.options.forEach(opt => {
          html += `<option value="${opt.value}">${opt.label}</option>`;
        });
        html += '</select>';
      } else if (field.type === 'textarea') {
        html += `<textarea name="${fieldName}" class="form-control" rows="2" 
                  placeholder="${field.placeholder || ''}" ${requiredAttr}></textarea>`;
      } else {
        const attrs = [];
        if (field.maxlength) attrs.push(`maxlength="${field.maxlength}"`);
        if (field.pattern) attrs.push(`pattern="${field.pattern}"`);
        if (field.min) attrs.push(`min="${field.min}"`);
        if (field.max) attrs.push(`max="${field.max}"`);
        if (field.value) attrs.push(`value="${field.value}"`);
        
        html += `<input type="${field.type}" name="${fieldName}" class="form-control" 
                  placeholder="${field.placeholder || ''}" ${attrs.join(' ')} ${requiredAttr}>`;
      }
      
      html += '</div></div>';
    });
    
    html += `
          </div>
        </div>
      </div>
    `;
    
    $container.html(html);
  }
  
  // =====================================
  // جمع بيانات الحقول
  // =====================================
  function collectPaymentData(method, containerSelector, fieldPrefix = '') {
    if (!method || !PAYMENT_METHODS[method]) {
      return {};
    }
    
    const data = { payment_method: method };
    const fields = PAYMENT_METHODS[method].fields;
    
    fields.forEach(field => {
      const fieldName = fieldPrefix ? `${fieldPrefix}_${field.name}` : field.name;
      const $field = $(`[name="${fieldName}"]`);
      if ($field.length) {
        data[field.name] = $field.val();
      }
    });
    
    return data;
  }
  
  // =====================================
  // تعبئة الحقول من البيانات
  // =====================================
  function populatePaymentFields(method, data, containerSelector, fieldPrefix = '') {
    if (!method || !data || !PAYMENT_METHODS[method]) {
      return;
    }
    
    const fields = PAYMENT_METHODS[method].fields;
    
    fields.forEach(field => {
      const fieldName = fieldPrefix ? `${fieldPrefix}_${field.name}` : field.name;
      const $field = $(`[name="${fieldName}"]`);
      if ($field.length && data[field.name]) {
        $field.val(data[field.name]);
      }
    });
  }
  
  // =====================================
  // API عامة
  // =====================================
  window.PaymentFieldsManager = {
    methods: PAYMENT_METHODS,
    render: renderPaymentFields,
    collect: collectPaymentData,
    populate: populatePaymentFields,
    
    // تهيئة تلقائية لعنصر select
    initSelector: function(selectSelector, containerSelector, fieldPrefix = '') {
      const $select = $(selectSelector);
      const $container = $(containerSelector);
      
      // رسم الحقول عند التغيير
      $select.on('change', function() {
        const method = $(this).val();
        renderPaymentFields(method, containerSelector, fieldPrefix);
      });
      
      // رسم الحقول الأولية إذا كانت هناك قيمة
      const initialMethod = $select.val();
      if (initialMethod) {
        renderPaymentFields(initialMethod, containerSelector, fieldPrefix);
      }
    },
    
    // الحصول على معلومات طريقة دفع
    getMethodInfo: function(method) {
      return PAYMENT_METHODS[method] || null;
    }
  };
  
})(jQuery);

