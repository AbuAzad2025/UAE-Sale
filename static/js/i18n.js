/**
 *  JavaScript Internationalization
 * نظام الترجمة في JavaScript
 */

// Get current language from session/cookie
function getCurrentLanguage() {
    // Try to get from body data attribute
    const lang = document.documentElement.lang || 'ar';
    return lang;
}

// Translation dictionary
const translations = {
    // Common
    'Save': { ar: 'حفظ', en: 'Save' },
    'Cancel': { ar: 'إلغاء', en: 'Cancel' },
    'Delete': { ar: 'حذف', en: 'Delete' },
    'Edit': { ar: 'تعديل', en: 'Edit' },
    'View': { ar: 'عرض', en: 'View' },
    'Back': { ar: 'رجوع', en: 'Back' },
    'Search': { ar: 'بحث', en: 'Search' },
    'Loading': { ar: 'جاري التحميل...', en: 'Loading...' },
    'Processing': { ar: 'جاري المعالجة...', en: 'Processing...' },
    
    // Messages
    'Success': { ar: 'نجاح', en: 'Success' },
    'Error': { ar: 'خطأ', en: 'Error' },
    'Warning': { ar: 'تحذير', en: 'Warning' },
    'Are you sure?': { ar: 'هل أنت متأكد؟', en: 'Are you sure?' },
    'This action cannot be undone': { ar: 'لا يمكن التراجع عن هذا الإجراء', en: 'This action cannot be undone' },
    'Saved successfully': { ar: 'تم الحفظ بنجاح', en: 'Saved successfully' },
    'Deleted successfully': { ar: 'تم الحذف بنجاح', en: 'Deleted successfully' },
    'Updated successfully': { ar: 'تم التحديث بنجاح', en: 'Updated successfully' },
    'An error occurred': { ar: 'حدث خطأ', en: 'An error occurred' },
    'Please try again': { ar: 'يرجى المحاولة مرة أخرى', en: 'Please try again' },
    
    // Actions
    'Confirm': { ar: 'تأكيد', en: 'Confirm' },
    'Yes': { ar: 'نعم', en: 'Yes' },
    'No': { ar: 'لا', en: 'No' },
    'OK': { ar: 'موافق', en: 'OK' },
    'Close': { ar: 'إغلاق', en: 'Close' },
    
    // Validation
    'This field is required': { ar: 'هذا الحقل مطلوب', en: 'This field is required' },
    'Please enter a valid email': { ar: 'يرجى إدخال بريد إلكتروني صحيح', en: 'Please enter a valid email' },
    'Please enter a valid phone number': { ar: 'يرجى إدخال رقم هاتف صحيح', en: 'Please enter a valid phone number' },
    'Please select an option': { ar: 'يرجى اختيار خيار', en: 'Please select an option' },
    
    // DataTables
    'Show': { ar: 'عرض', en: 'Show' },
    'entries': { ar: 'سجل', en: 'entries' },
    'Search:': { ar: 'بحث:', en: 'Search:' },
    'Showing': { ar: 'عرض', en: 'Showing' },
    'to': { ar: 'إلى', en: 'to' },
    'of': { ar: 'من', en: 'of' },
    'entries (filtered from': { ar: 'سجل (تمت فلترته من', en: 'entries (filtered from' },
    'total entries)': { ar: 'إجمالي السجلات)', en: 'total entries)' },
    'No data available': { ar: 'لا توجد بيانات', en: 'No data available' },
    'No records found': { ar: 'لم يتم العثور على سجلات', en: 'No records found' },
    'First': { ar: 'الأولى', en: 'First' },
    'Last': { ar: 'الأخيرة', en: 'Last' },
    'Next': { ar: 'التالي', en: 'Next' },
    'Previous': { ar: 'السابق', en: 'Previous' },
    'A new update is available. Do you want to refresh the page?': { ar: 'تحديث جديد متاح. هل تريد تحديث الصفحة؟', en: 'A new update is available. Do you want to refresh the page?' },
    'A server error occurred. Please try again.': { ar: 'حدث خطأ في الخادم. يرجى المحاولة مرة أخرى.', en: 'A server error occurred. Please try again.' },
    'AED': { ar: 'درهم', en: 'AED' },
    'Activate': { ar: 'تفعيل', en: 'Activate' },
    'Add New': { ar: 'إضافة جديد', en: 'Add New' },
    'Added': { ar: 'تمت إضافة', en: 'Added' },
    'Advanced Print Options': { ar: 'خيارات الطباعة المتقدمة', en: 'Advanced Print Options' },
    'All': { ar: 'الكل', en: 'All' },
    'Amount to settle:': { ar: 'المبلغ للتسوية:', en: 'Amount to settle:' },
    'An error occurred while preparing data for printing.': { ar: 'حدث خطأ أثناء تحضير البيانات للطباعة.', en: 'An error occurred while preparing data for printing.' },
    'An unexpected error occurred': { ar: 'حدث خطأ غير متوقع', en: 'An unexpected error occurred' },
    'Apply': { ar: 'تطبيق', en: 'Apply' },
    'Apply price': { ar: 'تطبيق السعر', en: 'Apply price' },
    'Approximate preview: Unable to reach the server. The final value is determined by the server on save.': { ar: 'معاينة تقريبية: تعذر الوصول إلى الخادم. القيمة النهائية يحددها الخادم عند الحفظ.', en: 'Approximate preview: Unable to reach the server. The final value is determined by the server on save.' },
    'Are you sure you want to delete this row?': { ar: 'هل أنت متأكد من حذف هذا السطر؟', en: 'Are you sure you want to delete this row?' },
    'Are you sure you want to delete?': { ar: 'هل أنت متأكد من الحذف؟', en: 'Are you sure you want to delete?' },
    'Available': { ar: 'المتوفر', en: 'Available' },
    'Average payment delay:': { ar: 'متوسط تأخير الدفع:', en: 'Average payment delay:' },
    'Bank Name': { ar: 'اسم البنك', en: 'Bank Name' },
    'Bank Transfer': { ar: 'تحويل بنكي', en: 'Bank Transfer' },
    'Barcode not found': { ar: 'الباركود غير موجود', en: 'Barcode not found' },
    'Based on': { ar: 'بناءً على', en: 'Based on' },
    'Bounced': { ar: 'مرتد', en: 'Bounced' },
    'Brief settlement statement': { ar: 'كشف تسوية مختصر', en: 'Brief settlement statement' },
    'Card Last 4 Digits': { ar: 'آخر 4 أرقام البطاقة', en: 'Card Last 4 Digits' },
    'Card Payment': { ar: 'دفع ببطاقة', en: 'Card Payment' },
    'Card Type': { ar: 'نوع البطاقة', en: 'Card Type' },
    'Cash Payment': { ar: 'دفع نقدي', en: 'Cash Payment' },
    'Cheque Number': { ar: 'رقم الشيك', en: 'Cheque Number' },
    'Cheque Payment': { ar: 'دفع بشيك', en: 'Cheque Payment' },
    'Cheque Status': { ar: 'حالة الشيك', en: 'Cheque Status' },
    'Choose an image first': { ar: 'اختر صورة أولاً', en: 'Choose an image first' },
    'Cleared': { ar: 'تم الصرف', en: 'Cleared' },
    'Close Window': { ar: 'إغلاق النافذة', en: 'Close Window' },
    'Close/Cancel': { ar: 'إغلاق/إلغاء', en: 'Close/Cancel' },
    'Compatible with:': { ar: 'متوافقة مع:', en: 'Compatible with:' },
    'Confirm delete': { ar: 'تأكيد الحذف', en: 'Confirm delete' },
    'Connection error': { ar: 'خطأ في الاتصال', en: 'Connection error' },
    'Connection failed': { ar: 'تعذر الاتصال', en: 'Connection failed' },
    'Connection timed out. Please try again.': { ar: 'انتهت مهلة الاتصال. يرجى المحاولة مرة أخرى.', en: 'Connection timed out. Please try again.' },
    'Copied successfully': { ar: 'تم النسخ بنجاح', en: 'Copied successfully' },
    'Cost:': { ar: 'التكلفة:', en: 'Cost:' },
    'Create New': { ar: 'إنشاء جديد', en: 'Create New' },
    'Credit': { ar: 'آجل (على الحساب)', en: 'Credit' },
    'Credit Days': { ar: 'مدة الائتمان (أيام)', en: 'Credit Days' },
    'Currency: AED - Prices and payment in AED': { ar: 'العملة: درهم - الأسعار والمدفوع بالدرهم', en: 'Currency: AED - Prices and payment in AED' },
    'Current balance:': { ar: 'الرصيد الحالي:', en: 'Current balance:' },
    'Customer Analysis': { ar: 'تحليل العميل', en: 'Customer Analysis' },
    'Data saved automatically': { ar: 'تم حفظ البيانات تلقائياً', en: 'Data saved automatically' },
    'Deactivate': { ar: 'تعطيل', en: 'Deactivate' },
    'Delete cheque': { ar: 'حذف شيك', en: 'Delete cheque' },
    'Delete customer': { ar: 'حذف زبون', en: 'Delete customer' },
    'Delete expense': { ar: 'حذف مصروف', en: 'Delete expense' },
    'Delete item': { ar: 'حذف الصنف', en: 'Delete item' },
    'Delete multiple': { ar: 'حذف متعدد', en: 'Delete multiple' },
    'Delete payment voucher': { ar: 'حذف سند صرف', en: 'Delete payment voucher' },
    'Delete product': { ar: 'حذف منتج', en: 'Delete product' },
    'Delete purchase invoice': { ar: 'حذف فاتورة شراء', en: 'Delete purchase invoice' },
    'Delete receipt voucher': { ar: 'حذف سند قبض', en: 'Delete receipt voucher' },
    'Delete sales invoice': { ar: 'حذف فاتورة مبيعات', en: 'Delete sales invoice' },
    'Delete supplier': { ar: 'حذف مورد', en: 'Delete supplier' },
    'Delete user': { ar: 'حذف مستخدم', en: 'Delete user' },
    'Delete warehouse': { ar: 'حذف مستودع', en: 'Delete warehouse' },
    'Deleted': { ar: 'تم الحذف', en: 'Deleted' },
    'Deleted {count} items successfully': { ar: 'تم حذف {count} عنصر بنجاح', en: 'Deleted {count} items successfully' },
    'Description': { ar: 'الوصف', en: 'Description' },
    'Designed by Azad Smart Systems Co.': { ar: 'تصميم شركة أزاد للأنظمة الذكية', en: 'Designed by Azad Smart Systems Co.' },
    'Direction:': { ar: 'الاتجاه:', en: 'Direction:' },
    'Disabled': { ar: 'غير مفعَل', en: 'Disabled' },
    'Discount': { ar: 'خصم', en: 'Discount' },
    'Do you want to restore': { ar: 'هل تريد استعادة', en: 'Do you want to restore' },
    'Due Date': { ar: 'تاريخ الاستحقاق', en: 'Due Date' },
    'E-Wallet': { ar: 'محفظة إلكترونية', en: 'E-Wallet' },
    'Enabled': { ar: 'مفعَل', en: 'Enabled' },
    'Entered exchange rate': { ar: 'سعر الصرف المدخل', en: 'Entered exchange rate' },
    'Entity:': { ar: 'الجهة:', en: 'Entity:' },
    'Error!': { ar: 'خطأ!', en: 'Error!' },
    'Example': { ar: 'مثال', en: 'Example' },
    'Exchange rate': { ar: 'سعر الصرف', en: 'Exchange rate' },
    'Exchange rate must be greater than zero': { ar: 'سعر الصرف يجب أن يكون أكبر من صفر', en: 'Exchange rate must be greater than zero' },
    'Exempt': { ar: 'معفاة', en: 'Exempt' },
    'Explanation': { ar: 'التوضيح', en: 'Explanation' },
    'Export Data': { ar: 'تصدير البيانات', en: 'Export Data' },
    'Exporting data...': { ar: 'جاري تصدير البيانات...', en: 'Exporting data...' },
    'Failed to create category': { ar: 'تعذر إنشاء الفئة', en: 'Failed to create category' },
    'Failed to load exchange rate': { ar: 'فشل تحميل سعر الصرف', en: 'Failed to load exchange rate' },
    'Failed to load exchange rate - please enter manually': { ar: 'فشل تحميل سعر الصرف - يرجى الإدخال يدوياً', en: 'Failed to load exchange rate - please enter manually' },
    'Failed to load payment fields': { ar: 'فشل تحميل حقول الدفع', en: 'Failed to load payment fields' },
    'Failed to load price': { ar: 'فشل تحميل السعر', en: 'Failed to load price' },
    'Failed to save the change': { ar: 'تعذّر حفظ التعديل', en: 'Failed to save the change' },
    'Fetch failed': { ar: 'فشل الجلب', en: 'Fetch failed' },
    'From page': { ar: 'من الصفحة', en: 'From page' },
    'From row': { ar: 'من السطر', en: 'From row' },
    'Global market price:': { ar: 'سعر السوق العالمي:', en: 'Global market price:' },
    'Go to Home': { ar: 'الذهاب للرئيسية', en: 'Go to Home' },
    'Hide/Show Menu': { ar: 'إخفاء/إظهار القائمة', en: 'Hide/Show Menu' },
    'Home': { ar: 'الرئيسية', en: 'Home' },
    'Incoming': { ar: 'وارد', en: 'Incoming' },
    'Info': { ar: 'معلومة', en: 'Info' },
    'Insufficient stock in this warehouse': { ar: 'المخزون في هذا المستودع غير كافٍ', en: 'Insufficient stock in this warehouse' },
    'Invoice': { ar: 'الفاتورة', en: 'Invoice' },
    'Item restored successfully': { ar: 'تم استعادة العنصر بنجاح', en: 'Item restored successfully' },
    'Items will be archived and financial records will be preserved': { ar: 'سيتم أرشفة العناصر والحفاظ على السجلات المالية', en: 'Items will be archived and financial records will be preserved' },
    'Keyboard Shortcuts': { ar: 'اختصارات لوحة المفاتيح', en: 'Keyboard Shortcuts' },
    'Keyboard Shortcuts (?)': { ar: 'اختصارات لوحة المفاتيح (?)', en: 'Keyboard Shortcuts (?)' },
    'Loaded.': { ar: 'تم التحميل.', en: 'Loaded.' },
    'Loading online data...': { ar: 'جاري تحميل بيانات الأونلاين...', en: 'Loading online data...' },
    'Markets:': { ar: 'الأسواق:', en: 'Markets:' },
    'Method:': { ar: 'الطريقة:', en: 'Method:' },
    'Name is required': { ar: 'الاسم مطلوب', en: 'Name is required' },
    'No additional fields required': { ar: 'لا توجد حقول إضافية مطلوبة', en: 'No additional fields required' },
    'No changes to save': { ar: 'لا يوجد أي تغيير للحفظ', en: 'No changes to save' },
    'No create button on this page': { ar: 'لا يوجد زر إنشاء في هذه الصفحة', en: 'No create button on this page' },
    'No internet connection': { ar: 'لا يوجد اتصال بالإنترنت', en: 'No internet connection' },
    'No online warehouse': { ar: 'لا يوجد أونلاين', en: 'No online warehouse' },
    'No online warehouse selected': { ar: 'لا يوجد مستودع أونلاين', en: 'No online warehouse selected' },
    'No results found': { ar: 'لا توجد نتائج', en: 'No results found' },
    'No rows match the print criteria.': { ar: 'لا توجد صفوف مطابقة للطباعة.', en: 'No rows match the print criteria.' },
    'No rows on the current page.': { ar: 'لا توجد صفوف في الصفحة الحالية.', en: 'No rows on the current page.' },
    'None': { ar: 'بلا', en: 'None' },
    'Note: The cheque will be archived if it is linked to vouchers, or permanently deleted if it is not linked.': { ar: 'تنبيه: سيتم أرشفة الشيك إذا كان مرتبطاً بسندات، أو حذفه نهائياً إذا كان غير مرتبط.', en: 'Note: The cheque will be archived if it is linked to vouchers, or permanently deleted if it is not linked.' },
    'Note: The customer will be archived if it has financial records, or permanently deleted if it is new.': { ar: 'تنبيه: سيتم أرشفة الزبون إذا كان له سجلات مالية، أو حذفه نهائياً إذا كان جديداً.', en: 'Note: The customer will be archived if it has financial records, or permanently deleted if it is new.' },
    'Note: The expense will be archived and the accounting entry will be reversed.': { ar: 'تنبيه: سيتم أرشفة المصروف وعكس القيد المحاسبي.', en: 'Note: The expense will be archived and the accounting entry will be reversed.' },
    'Note: The invoice will be archived if it has financial links (payments/cheques), or permanently deleted if it is not linked.': { ar: 'تنبيه: سيتم أرشفة الفاتورة إذا كان لها ارتباطات مالية (دفعات/شيكات)، أو حذفها نهائياً إذا كانت غير مرتبطة.', en: 'Note: The invoice will be archived if it has financial links (payments/cheques), or permanently deleted if it is not linked.' },
    'Note: The invoice will be archived if it has financial links, or permanently deleted if it is not linked.': { ar: 'تنبيه: سيتم أرشفة الفاتورة إذا كان لها ارتباطات مالية، أو حذفها نهائياً إذا كانت غير مرتبطة.', en: 'Note: The invoice will be archived if it has financial links, or permanently deleted if it is not linked.' },
    'Note: The product will be archived if it is linked to sale/purchase operations, or permanently deleted if it is not linked.': { ar: 'تنبيه: سيتم أرشفة المنتج إذا كان مرتبطاً بعمليات بيع/شراء، أو حذفه نهائياً إذا كان غير مرتبط.', en: 'Note: The product will be archived if it is linked to sale/purchase operations, or permanently deleted if it is not linked.' },
    'Note: The supplier will be archived if it has financial records, or permanently deleted if it is new.': { ar: 'تنبيه: سيتم أرشفة المورد إذا كان له سجلات مالية، أو حذفه نهائياً إذا كان جديداً.', en: 'Note: The supplier will be archived if it has financial records, or permanently deleted if it is new.' },
    'Note: The voucher will be archived if it is linked to cheques, or permanently deleted if it is not linked.': { ar: 'تنبيه: سيتم أرشفة السند إذا كان مرتبطاً بشيكات، أو حذفه نهائياً إذا كان غير مرتبط.', en: 'Note: The voucher will be archived if it is linked to cheques, or permanently deleted if it is not linked.' },
    'Note: The voucher will be archived if it is linked to other operations, or permanently deleted if it is not linked.': { ar: 'تنبيه: سيتم أرشفة السند إذا كان مرتبطاً بعمليات أخرى، أو حذفه نهائياً إذا كان غير مرتبط.', en: 'Note: The voucher will be archived if it is linked to other operations, or permanently deleted if it is not linked.' },
    'Note: The warehouse will be archived if it contains inventory movements, or permanently deleted if it is empty.': { ar: 'تنبيه: سيتم أرشفة المستودع إذا كان يحتوي على حركات مخزنية، أو حذفه نهائياً إذا كان فارغاً.', en: 'Note: The warehouse will be archived if it contains inventory movements, or permanently deleted if it is empty.' },
    'Online settings saved': { ar: 'تم حفظ إعدادات الأونلاين', en: 'Online settings saved' },
    'Open Customers': { ar: 'فتح الزبائن', en: 'Open Customers' },
    'Open Products': { ar: 'فتح المنتجات', en: 'Open Products' },
    'Open Sales': { ar: 'فتح المبيعات', en: 'Open Sales' },
    'Operation failed': { ar: 'فشل العملية', en: 'Operation failed' },
    'Other': { ar: 'أخرى', en: 'Other' },
    'Out of stock': { ar: 'غير متوفر', en: 'Out of stock' },
    'Outgoing': { ar: 'صادر', en: 'Outgoing' },
    'Paid': { ar: 'المدفوع', en: 'Paid' },
    'Partner': { ar: 'شريك', en: 'Partner' },
    'Payment details': { ar: 'تفاصيل الدفع', en: 'Payment details' },
    'Pending': { ar: 'معلق', en: 'Pending' },
    'Please add at least one product': { ar: 'يجب إضافة منتج واحد على الأقل', en: 'Please add at least one product' },
    'Please allow pop-ups to print the report.': { ar: 'يرجى السماح بالنوافذ المنبثقة لطباعة التقرير.', en: 'Please allow pop-ups to print the report.' },
    'Please enter a valid end page number not less than the start number.': { ar: 'يرجى إدخال رقم صفحة نهاية صحيح لا يقل عن رقم البداية.', en: 'Please enter a valid end page number not less than the start number.' },
    'Please enter a valid end row number not less than the start number.': { ar: 'يرجى إدخال رقم سطر نهاية صحيح لا يقل عن رقم البداية.', en: 'Please enter a valid end row number not less than the start number.' },
    'Please enter a valid start page number.': { ar: 'يرجى إدخال رقم صفحة بداية صحيح.', en: 'Please enter a valid start page number.' },
    'Please enter a valid start row number.': { ar: 'يرجى إدخال رقم سطر بداية صحيح.', en: 'Please enter a valid start row number.' },
    'Please enter the exchange rate manually': { ar: 'يرجى إدخال سعر الصرف يدوياً', en: 'Please enter the exchange rate manually' },
    'Please fill in all required fields': { ar: 'يرجى ملء جميع الحقول المطلوبة', en: 'Please fill in all required fields' },
    'Please select a customer': { ar: 'يجب اختيار زبون', en: 'Please select a customer' },
    'Please select a warehouse': { ar: 'يجب اختيار مستودع', en: 'Please select a warehouse' },
    'Press ? to show keyboard shortcuts': { ar: 'اضغط ? لعرض اختصارات لوحة المفاتيح', en: 'Press ? to show keyboard shortcuts' },
    'Price': { ar: 'السعر', en: 'Price' },
    'Print': { ar: 'طباعة', en: 'Print' },
    'Print all rows': { ar: 'طباعة جميع الصفوف', en: 'Print all rows' },
    'Print current page only': { ar: 'طباعة الصفحة الحالية فقط', en: 'Print current page only' },
    'Product': { ar: 'المنتج', en: 'Product' },
    'Product found': { ar: 'تم العثور على المنتج', en: 'Product found' },
    'Product not found': { ar: 'المنتج غير موجود', en: 'Product not found' },
    'Quantity': { ar: 'الكمية', en: 'Quantity' },
    'Quantity increased': { ar: 'تمت زيادة الكمية', en: 'Quantity increased' },
    'Quick Navigation': { ar: 'التنقل السريع', en: 'Quick Navigation' },
    'Quick Search': { ar: 'بحث سريع', en: 'Quick Search' },
    'Quick Tip': { ar: 'نصيحة سريعة', en: 'Quick Tip' },
    'Recommendation:': { ar: 'التوصية:', en: 'Recommendation:' },
    'Recommended': { ar: 'موصى به', en: 'Recommended' },
    'Restore item': { ar: 'استعادة العنصر', en: 'Restore item' },
    'Restored': { ar: 'تمت الاستعادة', en: 'Restored' },
    'Save Form': { ar: 'حفظ النموذج', en: 'Save Form' },
    'Saved': { ar: 'محفوظ', en: 'Saved' },
    'Saved.': { ar: 'تم الحفظ.', en: 'Saved.' },
    'Saving...': { ar: 'جارٍ الحفظ...', en: 'Saving...' },
    'Scan barcode': { ar: 'امسح الباركود', en: 'Scan barcode' },
    'Scan barcode then press Enter': { ar: 'امسح الباركود ثم Enter', en: 'Scan barcode then press Enter' },
    'Scan barcode to add a line item': { ar: 'امسح الباركود لإضافة بند', en: 'Scan barcode to add a line item' },
    'Scan barcode to add an item': { ar: 'امسح الباركود لإضافة صنف', en: 'Scan barcode to add an item' },
    'Search error': { ar: 'خطأ في البحث', en: 'Search error' },
    'Search for a customer...': { ar: 'ابحث عن زبون...', en: 'Search for a customer...' },
    'Search for a product...': { ar: 'ابحث عن منتج...', en: 'Search for a product...' },
    'Search for a supplier...': { ar: 'ابحث عن مورد...', en: 'Search for a supplier...' },
    'Searching...': { ar: 'جاري البحث...', en: 'Searching...' },
    'Select page range': { ar: 'تحديد مدى الصفحات', en: 'Select page range' },
    'Select row range': { ar: 'تحديد مدى الأسطر', en: 'Select row range' },
    'Select...': { ar: 'اختر...', en: 'Select...' },
    'Selected': { ar: 'تم اختيار', en: 'Selected' },
    'Settlement statement': { ar: 'كشف تسوية', en: 'Settlement statement' },
    'Shortcut': { ar: 'الاختصار', en: 'Shortcut' },
    'Show Help': { ar: 'عرض المساعدة', en: 'Show Help' },
    'Show Shortcuts': { ar: 'عرض الاختصارات', en: 'Show Shortcuts' },
    'Standard': { ar: 'قياسية', en: 'Standard' },
    'Stock:': { ar: 'المخزون:', en: 'Stock:' },
    'Success!': { ar: 'نجح!', en: 'Success!' },
    'Supplier': { ar: 'مورد', en: 'Supplier' },
    'System alert:': { ar: 'تنبيه النظام:', en: 'System alert:' },
    'Tax': { ar: 'الضريبة', en: 'Tax' },
    'The first page number exceeds the number of available pages.': { ar: 'رقم الصفحة الأولى يتجاوز عدد الصفحات المتاحة.', en: 'The first page number exceeds the number of available pages.' },
    'The first row number exceeds the number of available rows.': { ar: 'رقم السطر الأول يتجاوز عدد الصفوف المتاحة.', en: 'The first row number exceeds the number of available rows.' },
    'The print option was not recognized.': { ar: 'لم يتم التعرف على خيار الطباعة.', en: 'The print option was not recognized.' },
    'The table shows all rows on one page, select "All rows".': { ar: 'الجدول يعرض كل الصفوف في صفحة واحدة، اختر "جميع الصفوف".', en: 'The table shows all rows on one page, select "All rows".' },
    'The user will be deactivated, not permanently deleted': { ar: 'سيتم إلغاء تفعيل المستخدم وليس حذفه نهائياً', en: 'The user will be deactivated, not permanently deleted' },
    'This change will be documented in the operation log': { ar: 'سيتم توثيق هذا التغيير في سجل العمليات', en: 'This change will be documented in the operation log' },
    'This item': { ar: 'هذا العنصر', en: 'This item' },
    'To page': { ar: 'إلى الصفحة', en: 'To page' },
    'To row': { ar: 'إلى السطر', en: 'To row' },
    'Toggle dark mode': { ar: 'تبديل الوضع الليلي', en: 'Toggle dark mode' },
    'Total calculated by server.': { ar: 'الإجمالي محسوب بواسطة الخادم.', en: 'Total calculated by server.' },
    'Total cannot be negative': { ar: 'الإجمالي لا يمكن أن يكون سالب', en: 'Total cannot be negative' },
    'Transaction ID': { ar: 'رقم المعاملة', en: 'Transaction ID' },
    'Transaction Number': { ar: 'رقم المعاملة', en: 'Transaction Number' },
    'Transfer Date': { ar: 'تاريخ التحويل', en: 'Transfer Date' },
    'Transfer Reference': { ar: 'رقم الحوالة', en: 'Transfer Reference' },
    'Type:': { ar: 'النوع:', en: 'Type:' },
    'Unable to load data.': { ar: 'تعذر تحميل البيانات.', en: 'Unable to load data.' },
    'Unable to save': { ar: 'تعذر الحفظ', en: 'Unable to save' },
    'Unable to upload image': { ar: 'تعذر رفع الصورة', en: 'Unable to upload image' },
    'Unit price in AED': { ar: 'سعر الوحدة بالدرهم', en: 'Unit price in AED' },
    'Unknown error': { ar: 'خطأ غير معروف', en: 'Unknown error' },
    'Update failed': { ar: 'تعذر التحديث', en: 'Update failed' },
    'Updated': { ar: 'تم التحديث', en: 'Updated' },
    'Upload failed': { ar: 'فشل الرفع', en: 'Upload failed' },
    'Uploading image...': { ar: 'جاري رفع الصورة...', en: 'Uploading image...' },
    'Wallet Phone': { ar: 'رقم المحفظة', en: 'Wallet Phone' },
    'Wallet Provider': { ar: 'مزود المحفظة', en: 'Wallet Provider' },
    'Warehouse': { ar: 'المستودع', en: 'Warehouse' },
    'Warning!': { ar: 'تحذير!', en: 'Warning!' },
    'Warning: Low stock for product': { ar: 'تنبيه: المخزون منخفض للمنتج', en: 'Warning: Low stock for product' },
    'Will delete': { ar: 'سيتم حذف', en: 'Will delete' },
    'Yes, delete': { ar: 'نعم، احذف', en: 'Yes, delete' },
    'Yes, delete all': { ar: 'نعم، احذف الكل', en: 'Yes, delete all' },
    'Yes, restore': { ar: 'نعم، استعد', en: 'Yes, restore' },
    'You must select at least one item': { ar: 'يجب اختيار عنصر واحد على الأقل', en: 'You must select at least one item' },
    'Zero 0%': { ar: 'صفرية 0%', en: 'Zero 0%' },
    'and': { ar: 'و', en: 'and' },
    'but there is nowhere to add it': { ar: 'لكن لا يوجد مكان لإضافته', en: 'but there is nowhere to add it' },
    'by': { ar: 'بنسبة', en: 'by' },
    'days': { ar: 'يوم', en: 'days' },
    'in': { ar: 'بالـ', en: 'in' },
    'in AED': { ar: 'بالدرهم', en: 'in AED' },
    'in stock': { ar: 'متوفر', en: 'in stock' },
    'is higher than server': { ar: 'أعلى من السيرفر', en: 'is higher than server' },
    'is lower than server rate': { ar: 'أقل من سعر السيرفر', en: 'is lower than server rate' },
    'item(s)': { ar: 'عنصر', en: 'item(s)' },
    'others': { ar: 'أخرى', en: 'others' },
    'transactions': { ar: 'معاملات', en: 'transactions' },
};

/**
 * Translate a key
 * @param {string} key - The translation key
 * @param {Object} params - Optional parameters for string interpolation
 * @returns {string} Translated text
 */
function t(key, params = {}) {
    const lang = getCurrentLanguage();
    const translation = translations[key];
    
    if (!translation) {        return key;
    }
    
    let text = translation[lang] || translation['ar'] || key;
    
    // Replace parameters {param}
    Object.keys(params).forEach(param => {
        text = text.replace(`{${param}}`, params[param]);
    });
    
    return text;
}

/**
 * Translate all elements with data-i18n attribute
 */
function translatePage() {
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        element.textContent = t(key);
    });
}

/**
 * Get DataTables language configuration
 */
function getDataTablesLanguage() {
    const lang = getCurrentLanguage();
    
    if (lang === 'ar') {
        return {
            url: '/static/datatables/Arabic.json'
        };
    }
    
    return {
        "sEmptyTable": t("No data available"),
        "sInfo": `${t("Showing")} _START_ ${t("to")} _END_ ${t("of")} _TOTAL_ ${t("entries")}`,
        "sInfoEmpty": `${t("Showing")} 0 ${t("to")} 0 ${t("of")} 0 ${t("entries")}`,
        "sInfoFiltered": `(${t("entries (filtered from")} _MAX_ ${t("total entries)")})`,
        "sLengthMenu": `${t("Show")} _MENU_ ${t("entries")}`,
        "sLoadingRecords": t("Loading") + "...",
        "sProcessing": t("Processing") + "...",
        "sSearch": t("Search:"),
        "sZeroRecords": t("No records found"),
        "oPaginate": {
            "sFirst": t("First"),
            "sLast": t("Last"),
            "sNext": t("Next"),
            "sPrevious": t("Previous")
        }
    };
}

/**
 * Show SweetAlert with translation
 */
function showAlert(title, text, icon = 'info') {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: t(title),
            text: t(text),
            icon: icon,
            confirmButtonText: t('OK')
        });
    } else {
        alert(`${t(title)}\n${t(text)}`);
    }
}

/**
 * Show confirmation dialog with translation
 */
function confirmAction(title, text, onConfirm) {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: t(title),
            text: t(text),
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: t('Yes'),
            cancelButtonText: t('No'),
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6'
        }).then((result) => {
            if (result.isConfirmed && onConfirm) {
                onConfirm();
            }
        });
    } else {
        if (confirm(`${t(title)}\n${t(text)}`)) {
            if (onConfirm) onConfirm();
        }
    }
}

// Export functions
window.t = t;
window.translatePage = translatePage;
window.getDataTablesLanguage = getDataTablesLanguage;
window.showAlert = showAlert;
window.confirmAction = confirmAction;

// Auto-translate on page load
document.addEventListener('DOMContentLoaded', function() {
    translatePage();
});

