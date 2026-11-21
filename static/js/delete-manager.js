/**
 *  Delete Manager - نظام حذف موحد واحترافي
 * إدارة عمليات الحذف في كل النظام مع تأكيد وأرشفة
 */

(function($) {
  'use strict';
  
  // =====================================
  // حذف عنصر عام
  // =====================================
  window.deleteItem = function(itemType, itemId, itemName, redirectUrl) {
    // رسائل مخصصة حسب نوع العنصر
    const messages = {
      'customers': { title: t('Delete customer'), text: t('Note: The customer will be archived if it has financial records, or permanently deleted if it is new.'), url: `/customers/${itemId}/delete` },
      'suppliers': { title: t('Delete supplier'), text: t('Note: The supplier will be archived if it has financial records, or permanently deleted if it is new.'), url: `/suppliers/${itemId}/delete` },
      'products': { title: t('Delete product'), text: t('Note: The product will be archived if it is linked to sale/purchase operations, or permanently deleted if it is not linked.'), url: `/products/${itemId}/delete` },
      'sales': { title: t('Delete sales invoice'), text: t('Note: The invoice will be archived if it has financial links (payments/cheques), or permanently deleted if it is not linked.'), url: `/sales/${itemId}/delete` },
      'purchases': { title: t('Delete purchase invoice'), text: t('Note: The invoice will be archived if it has financial links, or permanently deleted if it is not linked.'), url: `/purchases/${itemId}/delete` },
      'receipts': { title: t('Delete receipt voucher'), text: t('Note: The voucher will be archived if it is linked to cheques, or permanently deleted if it is not linked.'), url: `/payments/receipts/${itemId}/delete` },
      'payments': { title: t('Delete payment voucher'), text: t('Note: The voucher will be archived if it is linked to other operations, or permanently deleted if it is not linked.'), url: `/payments/payments/${itemId}/delete` },
      'expenses': { title: t('Delete expense'), text: t('Note: The expense will be archived and the accounting entry will be reversed.'), url: `/expenses/${itemId}/delete` },
      'cheques': { title: t('Delete cheque'), text: t('Note: The cheque will be archived if it is linked to vouchers, or permanently deleted if it is not linked.'), url: `/cheques/${itemId}/delete` },
      'users': { title: t('Delete user'), text: t('The user will be deactivated, not permanently deleted'), url: `/users/${itemId}/delete` },
      'warehouses': { title: t('Delete warehouse'), text: t('Note: The warehouse will be archived if it contains inventory movements, or permanently deleted if it is empty.'), url: `/warehouse/${itemId}/delete` }
    };
    
    const msg = messages[itemType] || { title: t('Delete'), text: t('Are you sure you want to delete?'), url: `/${itemType}/${itemId}/delete` };
    
    Swal.fire({
      title: msg.title,
      html: `
        <p><strong>${itemName}</strong></p>
        <p class="text-muted">${msg.text}</p>
      `,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#d33',
      cancelButtonColor: '#6c757d',
      confirmButtonText: `<i class="fas fa-trash mr-2"></i>${t('Yes, delete')}`,
      cancelButtonText: `<i class="fas fa-times mr-2"></i>${t('Cancel')}`,
      reverseButtons: true,
      showLoaderOnConfirm: true,
      preConfirm: function() {
        // إنشاء form وإرساله
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = msg.url;
        
        // إضافة CSRF token
        const csrfInput = document.createElement('input');
        csrfInput.type = 'hidden';
        csrfInput.name = 'csrf_token';
        csrfInput.value = document.querySelector('input[name="csrf_token"]')?.value || 
                          document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        form.appendChild(csrfInput);
        
        document.body.appendChild(form);
        form.submit();
        
        // منع إغلاق التنبيه
        return new Promise(() => {});
      },
      allowOutsideClick: () => !Swal.isLoading()
    });
  };
  
  // =====================================
  // حذف عدة عناصر
  // =====================================
  window.deleteMultiple = function(itemIds, itemType, redirectUrl) {
    if (!itemIds || itemIds.length === 0) {
      toastr.warning(' ' + t('You must select at least one item'));
      return;
    }
    
    Swal.fire({
      title: t('Delete multiple'),
      html: `
        <p>${t('Will delete')} <strong>${itemIds.length}</strong> ${t('item(s)')}</p>
        <p class="text-muted">${t('Items will be archived and financial records will be preserved')}</p>
      `,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#d33',
      cancelButtonColor: '#6c757d',
      confirmButtonText: `<i class="fas fa-trash mr-2"></i>${t('Yes, delete all')}`,
      cancelButtonText: `<i class="fas fa-times mr-2"></i>${t('Cancel')}`,
      reverseButtons: true,
      showLoaderOnConfirm: true,
      preConfirm: function() {
        return $.ajax({
          url: `/${itemType}s/delete-multiple`,
          method: 'POST',
          data: JSON.stringify({ ids: itemIds }),
          contentType: 'application/json',
          headers: {
            'X-CSRFToken': $('input[name="csrf_token"]').val() || $('meta[name="csrf-token"]').attr('content')
          }
        }).then(function(response) {
          return response;
        }).catch(function(error) {
          Swal.showValidationMessage(`${t('An error occurred')}: ${error.responseJSON?.message || t('Unknown error')}`);
        });
      },
      allowOutsideClick: () => !Swal.isLoading()
    }).then(function(result) {
      if (result.isConfirmed) {
        Swal.fire({
          icon: 'success',
          title: t('Deleted successfully'),
          text: t('Deleted {count} items successfully', { count: itemIds.length }),
          timer: 2000,
          showConfirmButton: false
        }).then(function() {
          if (redirectUrl) {
            window.location.href = redirectUrl;
          } else {
            location.reload();
          }
        });
      }
    });
  };
  
  // =====================================
  // حذف سطر (في الجداول)
  // =====================================
  window.deleteTableRow = function(rowElement, confirmMessage = t('Are you sure you want to delete?')) {
    Swal.fire({
      title: t('Confirm delete'),
      text: confirmMessage,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#d33',
      cancelButtonColor: '#6c757d',
      confirmButtonText: `<i class="fas fa-trash mr-2"></i>${t('Yes')}`,
      cancelButtonText: `<i class="fas fa-times mr-2"></i>${t('Cancel')}`,
      reverseButtons: true
    }).then(function(result) {
      if (result.isConfirmed) {
        $(rowElement).fadeOut(300, function() {
          $(this).remove();
          toastr.success(' ' + t('Deleted'));
        });
      }
    });
  };
  
  // =====================================
  // استعادة عنصر محذوف
  // =====================================
  window.restoreItem = function(itemId, itemType, itemName) {
    Swal.fire({
      title: t('Restore item'),
      html: `<p>${t('Do you want to restore')}: <strong>${itemName}</strong>?</p>`,
      icon: 'question',
      showCancelButton: true,
      confirmButtonColor: '#28a745',
      cancelButtonColor: '#6c757d',
      confirmButtonText: `<i class="fas fa-undo mr-2"></i>${t('Yes, restore')}`,
      cancelButtonText: `<i class="fas fa-times mr-2"></i>${t('Cancel')}`,
      reverseButtons: true,
      showLoaderOnConfirm: true,
      preConfirm: function() {
        return $.ajax({
          url: `/${itemType}s/${itemId}/restore`,
          method: 'POST',
          headers: {
            'X-CSRFToken': $('input[name="csrf_token"]').val() || $('meta[name="csrf-token"]').attr('content')
          }
        }).then(function(response) {
          return response;
        }).catch(function(error) {
          Swal.showValidationMessage(`${t('An error occurred')}: ${error.responseJSON?.message || t('Unknown error')}`);
        });
      },
      allowOutsideClick: () => !Swal.isLoading()
    }).then(function(result) {
      if (result.isConfirmed) {
        Swal.fire({
          icon: 'success',
          title: t('Restored'),
          text: t('Item restored successfully'),
          timer: 2000,
          showConfirmButton: false
        }).then(function() {
          location.reload();
        });
      }
    });
  };
  
  // =====================================
  // تهيئة أزرار الحذف التلقائية
  // =====================================
  $(document).on('click', '[data-delete-item]', function(e) {
    e.preventDefault();
    const $btn = $(this);
    const itemId = $btn.data('delete-item');
    const itemType = $btn.data('item-type');
    const itemName = $btn.data('item-name') || t('This item');
    const redirectUrl = $btn.data('redirect-url');
    
    deleteItem(itemId, itemType, itemName, redirectUrl);
  });
  
  $(document).on('click', '[data-delete-row]', function(e) {
    e.preventDefault();
    const $btn = $(this);
    const rowElement = $btn.closest('tr, .product-line, [data-row]');
    const confirmMessage = $btn.data('confirm-message') || t('Are you sure you want to delete this row?');
    
    deleteTableRow(rowElement, confirmMessage);
  });
  
  $(document).on('click', '[data-restore-item]', function(e) {
    e.preventDefault();
    const $btn = $(this);
    const itemId = $btn.data('restore-item');
    const itemType = $btn.data('item-type');
    const itemName = $btn.data('item-name') || t('This item');
    
    restoreItem(itemId, itemType, itemName);
  });
  
})(jQuery);

