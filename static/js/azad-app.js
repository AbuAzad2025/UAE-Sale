/**
 * Azad Garage System - Main JavaScript
 * نظام أزاد للكراج - الجافا سكريبت الرئيسي
 */

$(document).ready(function() {
    // Initialize all components
    initializeApp();
});

/**
 * Initialize Application
 */
function initializeApp() {
    initializeSelect2();
    initializeDataTables();
    initializeTooltips();
    initializeAlerts();
    initializeFormValidation();
    initializeNumberFormatting();
    initializeAccessibility();
}

/**
 * Initialize Select2 for all select elements
 */
function initializeSelect2() {
    if ($.fn.select2) {
        $('.select2').select2({
            theme: 'bootstrap4',
            language: 'ar',
            dir: 'rtl',
            width: '100%',
            placeholder: 'اختر...'
        });
    }
}

/**
 * Initialize DataTables with Arabic language
 */
function initializeDataTables() {
    if ($.fn.DataTable) {
        $('.datatable').DataTable({
            language: {
                url: '/static/datatables/Arabic.json'
            },
            responsive: true,
            pageLength: 25,
            lengthMenu: [[10, 25, 50, 100, -1], [10, 25, 50, 100, "الكل"]],
            dom: 'Bfrtip',
            buttons: [
                {
                    extend: 'excel',
                    text: '<i class="fas fa-file-excel"></i> Excel',
                    className: 'btn btn-success btn-sm'
                },
                {
                    extend: 'pdf',
                    text: '<i class="fas fa-file-pdf"></i> PDF',
                    className: 'btn btn-danger btn-sm'
                },
                {
                    extend: 'print',
                    text: '<i class="fas fa-print"></i> طباعة',
                    className: 'btn btn-info btn-sm'
                }
            ]
        });
    }
}

/**
 * Initialize Bootstrap Tooltips
 */
function initializeTooltips() {
    $('[data-toggle="tooltip"]').tooltip();
}

/**
 * Auto-hide alerts after 5 seconds
 */
function initializeAlerts() {
    setTimeout(function() {
        $('.alert:not(.flash-message):not(.alert-permanent)').fadeOut('slow');
    }, 5000);
}

/**
 * Form Validation
 */
function initializeFormValidation() {
    $('form').on('submit', function(e) {
        const form = $(this);
        
        // Check required fields
        let isValid = true;
        form.find('[required]').each(function() {
            if (!$(this).val()) {
                isValid = false;
                $(this).addClass('is-invalid');
                showError('يرجى ملء جميع الحقول المطلوبة');
                return false;
            } else {
                $(this).removeClass('is-invalid');
            }
        });
        
        if (!isValid) {
            e.preventDefault();
            return false;
        }
        
        // Show loading
        showLoading();
    });
}

/**
 * Number Formatting for Arabic
 */
function initializeNumberFormatting() {
    $('.number-format').each(function() {
        const value = parseFloat($(this).text());
        if (!isNaN(value)) {
            $(this).text(formatNumber(value));
        }
    });
}

/**
 * Format number with commas
 */
function formatNumber(num, decimals = 2) {
    return num.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * Show Loading Spinner
 */
function showLoading() {
    const html = `
        <div class="loading-overlay" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 9999; display: flex; align-items: center; justify-content: center;">
            <div class="loading-spinner"></div>
        </div>
    `;
    $('body').append(html);
}

/**
 * Hide Loading Spinner
 */
function hideLoading() {
    $('.loading-overlay').remove();
}

/**
 * Show Success Message
 */
function showSuccess(message) {
    showAlert(message, 'success');
}

/**
 * Show Error Message
 */
function showError(message) {
    showAlert(message, 'danger');
}

/**
 * Show Alert
 */
function showAlert(message, type = 'info') {
    const html = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert" style="position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 10000; min-width: 300px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
            ${message}
            <button type="button" class="close" data-dismiss="alert">
                <span>&times;</span>
            </button>
        </div>
    `;
    $('body').append(html);
    
    // إخفاء تلقائي بعد 10 ثواني (بدلاً من 5)
    setTimeout(function() {
        $('.alert').fadeOut(1500, function() {
            $(this).remove();
        });
    }, 10000);
}

/**
 * Confirm Delete
 */
function confirmDelete(message = 'هل أنت متأكد من الحذف؟') {
    return confirm(message);
}

/**
 * Print Element
 */
function printElement(elementId) {
    const content = document.getElementById(elementId).innerHTML;
    const originalContent = document.body.innerHTML;
    document.body.innerHTML = content;
    window.print();
    document.body.innerHTML = originalContent;
    location.reload();
}

/**
 * Copy to Clipboard
 */
function copyToClipboard(text) {
    const temp = $('<input>');
    $('body').append(temp);
    temp.val(text).select();
    document.execCommand('copy');
    temp.remove();
    showSuccess('تم النسخ بنجاح');
}

/**
 * Calculate Totals (for sales/purchase forms)
 */
// حساب الإجماليات - Backend Calculation (used as fallback/legacy)
// NOTE: This is now replaced by sales-enhanced.js for modern pages
async function calculateTotals() {
    try {
        // Detect which type of form (sales or purchases)
        const isSalesForm = $('[name^="lines"][name$="[unit_price]"]').length > 0;
        const isPurchaseForm = $('[name^="lines"][name$="[unit_cost]"]').length > 0;
        
        if (isSalesForm) {
            // Use sales API
            const lines = [];
            $('[name^="lines"][name$="[quantity]"]').each(function() {
                const $line = $(this).closest('.product-line');
                const qty = parseFloat($(this).val()) || 0;
                const price = parseFloat($line.find('[name$="[unit_price]"]').val()) || 0;
                const discount = parseFloat($line.find('[name$="[discount_percent]"]').val()) || 0;
                
                if (qty > 0 || price > 0) {
                    lines.push({
                        quantity: qty,
                        unit_price: price,
                        discount_percent: discount
                    });
                }
            });
            
            const response = await fetch('/sales/api/calculate-totals', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    lines: lines,
                    discount_amount: parseFloat($('[name="discount_amount"]').val()) || 0,
                    shipping_cost: parseFloat($('[name="shipping_cost"]').val()) || 0,
                    tax_rate: parseFloat($('[name="tax_rate"]').val()) || 0
                })
            });
            
            const result = await response.json();
            if (result.success) {
                $('#subtotal').text(formatNumber(result.subtotal));
                $('#total').text(formatNumber(result.total));
                return {
                    subtotal: result.subtotal,
                    discount: result.discount,
                    shipping: result.shipping,
                    tax: result.tax_amount,
                    total: result.total
                };
            }
        }
        
        // Fallback to client-side
        return calculateTotalsClientSide();
    } catch (error) {
        console.error('Backend calculation failed, using client-side:', error);
        return calculateTotalsClientSide();
    }
}

// Client-side fallback calculation
function calculateTotalsClientSide() {
    let subtotal = 0;
    
    $('[name^="lines"][name$="[quantity]"]').each(function() {
        const qty = parseFloat($(this).val()) || 0;
        const price = parseFloat($(this).closest('.product-line').find('[name$="[unit_price]"]').val()) || 0;
        const discount = parseFloat($(this).closest('.product-line').find('[name$="[discount_percent]"]').val()) || 0;
        const lineTotal = qty * price * (1 - discount/100);
        subtotal += lineTotal;
    });
    
    const discount = parseFloat($('[name="discount_amount"]').val()) || 0;
    const shipping = parseFloat($('[name="shipping_cost"]').val()) || 0;
    const taxRate = parseFloat($('[name="tax_rate"]').val()) || 0;
    
    const afterDiscount = subtotal - discount + shipping;
    const tax = afterDiscount * (taxRate / 100);
    const total = afterDiscount + tax;
    
    $('#subtotal').text(formatNumber(subtotal));
    $('#total').text(formatNumber(total));
    
    return {
        subtotal: subtotal,
        discount: discount,
        shipping: shipping,
        tax: tax,
        total: total
    };
}

/**
 * Load Exchange Rate
 */
function loadExchangeRate(fromCurrency, toCurrency = 'AED') {
    if (fromCurrency === toCurrency) {
        $('#exchange_rate').val('1.00');
        return;
    }
    
    $.ajax({
        url: `/api/currency-rate/${fromCurrency}/${toCurrency}`,
        method: 'GET',
        success: function(data) {
            if (data.rate) {
                $('#exchange_rate').val(data.rate.toFixed(6));
            }
        },
        error: function() {
            showError('فشل تحميل سعر الصرف');
        }
    });
}

/**
 * Search Products (Autocomplete)
 */
function initializeProductSearch() {
    $('.product-search').autocomplete({
        source: function(request, response) {
            $.ajax({
                url: '/api/search',
                data: {
                    q: request.term,
                    type: 'products'
                },
                success: function(data) {
                    response(data.results.map(function(item) {
                        return {
                            label: item.name,
                            value: item.id,
                            price: item.regular_price
                        };
                    }));
                }
            });
        },
        minLength: 2,
        select: function(event, ui) {
            // Handle product selection
            $(this).data('product-id', ui.item.value);
            $(this).val(ui.item.label);
            return false;
        }
    });
}

/**
 * Search Customers (Autocomplete)
 */
function initializeCustomerSearch() {
    $('.customer-search').autocomplete({
        source: function(request, response) {
            $.ajax({
                url: '/api/search',
                data: {
                    q: request.term,
                    type: 'customers'
                },
                success: function(data) {
                    response(data.results.map(function(item) {
                        return {
                            label: item.name + ' - ' + item.phone,
                            value: item.id
                        };
                    }));
                }
            });
        },
        minLength: 2
    });
}

/**
 * Accessibility Features
 */
function initializeAccessibility() {
    // Keyboard shortcuts
    $(document).keydown(function(e) {
        // Alt + N = New Sale
        if (e.altKey && e.keyCode === 78) {
            window.location.href = '/sales/create';
        }
        
        // Alt + C = Customers
        if (e.altKey && e.keyCode === 67) {
            window.location.href = '/customers';
        }
        
        // Alt + P = Products
        if (e.altKey && e.keyCode === 80) {
            window.location.href = '/products';
        }
        
        // Ctrl + P = Print
        if (e.ctrlKey && e.keyCode === 80) {
            e.preventDefault();
            window.print();
        }
    });
    
    // Large text toggle
    $('#large-text-toggle').on('click', function() {
        $('body').toggleClass('large-text');
    });
    
    // High contrast toggle
    $('#high-contrast-toggle').on('click', function() {
        $('body').toggleClass('high-contrast');
    });
}

/**
 * WhatsApp Share
 */
function shareOnWhatsApp(text, phone = '') {
    const url = `https://wa.me/${phone}?text=${encodeURIComponent(text)}`;
    window.open(url, '_blank');
}

/**
 * Export to Excel
 */
function exportToExcel(tableId, filename = 'export') {
    const table = document.getElementById(tableId);
    const wb = XLSX.utils.table_to_book(table);
    XLSX.writeFile(wb, filename + '.xlsx');
}

/**
 * Check Internet Connection
 */
function checkConnection() {
    if (!navigator.onLine) {
        showError('لا يوجد اتصال بالإنترنت');
        return false;
    }
    return true;
}

// Global error handler
window.onerror = function(msg, url, lineNo, columnNo, error) {
    console.error('Error: ' + msg + '\nURL: ' + url + '\nLine: ' + lineNo);
    showError('حدث خطأ غير متوقع');
    return false;
};

// Export functions for global use
window.azad = {
    showLoading: showLoading,
    hideLoading: hideLoading,
    showSuccess: showSuccess,
    showError: showError,
    showAlert: showAlert,
    confirmDelete: confirmDelete,
    printElement: printElement,
    copyToClipboard: copyToClipboard,
    calculateTotals: calculateTotals,
    loadExchangeRate: loadExchangeRate,
    shareOnWhatsApp: shareOnWhatsApp,
    formatNumber: formatNumber
};

/**
 * UI Helper Object - Provides toast notifications
 * Integrates with the existing notify system from notifications.js
 */
window.UI = {
    /**
     * Show toast notification
     * @param {string} message - The message to display
     * @param {string} type - Type of toast (success, error, warning, info)
     * @param {number} duration - Duration in milliseconds (default: 4000)
     */
    toast: function(message, type = 'info', duration = 4000) {
        // Check if the notify object exists (from notifications.js)
        if (typeof window.notify !== 'undefined') {
            return window.notify.show({ 
                type: type, 
                message: message, 
                duration: duration 
            });
        }
        // Fallback to SweetAlert2 if available
        else if (typeof Swal !== 'undefined') {
            const icons = {
                'success': 'success',
                'error': 'error',
                'warning': 'warning',
                'info': 'info'
            };
            Swal.fire({
                icon: icons[type] || 'info',
                text: message,
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: duration,
                timerProgressBar: true
            });
        }
        // Final fallback to alert
        else {
            showAlert(message, type === 'error' ? 'danger' : type);
        }
    },
    
    /**
     * Show success toast
     */
    success: function(message, duration = 4000) {
        this.toast(message, 'success', duration);
    },
    
    /**
     * Show error toast
     */
    error: function(message, duration = 4000) {
        this.toast(message, 'error', duration);
    },
    
    /**
     * Show warning toast
     */
    warning: function(message, duration = 4000) {
        this.toast(message, 'warning', duration);
    },
    
    /**
     * Show info toast
     */
    info: function(message, duration = 4000) {
        this.toast(message, 'info', duration);
    }
};

