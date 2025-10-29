"""
Error Messages - رسائل الأخطاء الموحدة والواضحة
جميع الرسائل بالعربية مع hints ومساعدة
"""


class ErrorMessages:
    """رسائل خطأ موحدة وواضحة"""
    
    # =====================================
    # المستخدمين
    # =====================================
    
    @staticmethod
    def user_required_fields():
        return '⚠️ اسم المستخدم وكلمة المرور مطلوبان.\n💡 تأكد من ملء جميع الحقول المطلوبة.'
    
    @staticmethod
    def user_exists(username):
        from datetime import datetime
        year = datetime.now().year
        return (f'⚠️ اسم المستخدم "{username}" موجود مسبقاً.\n'
                f'💡 جرب أحد هذه البدائل:\n'
                f'   • {username}_{year}\n'
                f'   • {username}_admin\n'
                f'   • {username}123')
    
    @staticmethod
    def weak_password(errors):
        hints = '\n   • '.join(errors)
        return (f'🔒 كلمة المرور لا تستوفي المتطلبات:\n   • {hints}\n\n'
                f'💡 مثال على كلمة مرور قوية: Ahmed@2024!\n'
                f'💡 استخدم مزيج من الحروف الكبيرة والصغيرة والأرقام والرموز')
    
    @staticmethod
    def password_mismatch():
        return '⚠️ كلمتا المرور غير متطابقتين.\n💡 تأكد من كتابة نفس كلمة المرور في الحقلين.'
    
    @staticmethod
    def user_update_failed(error):
        return f'❌ فشل تحديث بيانات المستخدم.\n📝 الخطأ: {error}\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.'
    
    @staticmethod
    def user_delete_self():
        return '⚠️ لا يمكنك حذف حسابك الخاص.\n💡 اطلب من مستخدم آخر أن يقوم بذلك.'
    
    @staticmethod
    def user_delete_owner():
        return '⚠️ لا يمكن حذف حساب المالك.\n💡 حساب المالك محمي بشكل دائم للأمان.'
    
    # =====================================
    # العملاء
    # =====================================
    
    @staticmethod
    def customer_required_fields():
        return '⚠️ الاسم ورقم الهاتف مطلوبان.\n💡 أدخل على الأقل اسم العميل ورقم هاتفه.'
    
    @staticmethod
    def customer_phone_invalid():
        return '📱 رقم الهاتف غير صحيح.\n💡 أدخل رقم هاتف صالح مثل: 0501234567 أو +971501234567'
    
    @staticmethod
    def customer_email_invalid():
        return '📧 البريد الإلكتروني غير صحيح.\n💡 تأكد من وجود @ ونطاق مثل: ahmed@example.com'
    
    @staticmethod
    def customer_has_transactions(name):
        return (f'⚠️ لا يمكن حذف العميل "{name}" لأن لديه معاملات مسجلة.\n'
                f'💡 سيتم إلغاء تفعيله بدلاً من حذفه للحفاظ على السجلات.')
    
    # =====================================
    # المنتجات
    # =====================================
    
    @staticmethod
    def product_required_fields():
        return '⚠️ اسم المنتج والسعر مطلوبان.\n💡 أدخل على الأقل اسم المنتج وسعر البيع.'
    
    @staticmethod
    def product_sku_exists(sku):
        return f'⚠️ رمز المنتج (SKU) "{sku}" موجود مسبقاً.\n💡 استخدم رمز فريد أو اترك الحقل فارغاً للتوليد التلقائي.'
    
    @staticmethod
    def product_negative_stock():
        return '⚠️ لا يمكن أن يكون المخزون سالباً.\n💡 تأكد من إدخال كمية صحيحة أو اضبط على صفر.'
    
    @staticmethod
    def product_low_stock(name, current, min_required):
        return (f'⚠️ المنتج "{name}" مخزونه منخفض!\n'
                f'📦 المتوفر: {current} | الحد الأدنى: {min_required}\n'
                f'💡 احذر من نفاد الكمية. قم بالطلب من المورد.')
    
    @staticmethod
    def product_out_of_stock(name):
        return f'❌ المنتج "{name}" نفد من المخزون.\n💡 لا يمكن البيع. اطلب كمية جديدة من المورد.'
    
    # =====================================
    # المبيعات
    # =====================================
    
    @staticmethod
    def sale_no_lines():
        return '⚠️ يجب إضافة منتج واحد على الأقل للفاتورة.\n💡 اضغط زر "➕ إضافة صف" واختر منتجاً.'
    
    @staticmethod
    def sale_no_customer():
        return '⚠️ يجب اختيار عميل للفاتورة.\n💡 اختر عميل من القائمة أو أضف عميل جديد.'
    
    @staticmethod
    def sale_insufficient_stock(product_name, available, requested):
        return (f'❌ كمية غير كافية للمنتج "{product_name}"!\n'
                f'📦 المتوفر: {available} | المطلوب: {requested}\n'
                f'💡 قلل الكمية أو اطلب مخزون جديد.')
    
    @staticmethod
    def sale_invalid_quantity():
        return '⚠️ الكمية يجب أن تكون أكبر من صفر.\n💡 أدخل كمية صحيحة مثل: 1, 2, 5, 10'
    
    @staticmethod
    def sale_invalid_price():
        return '⚠️ السعر يجب أن يكون أكبر من صفر.\n💡 أدخل سعر صحيح بالدرهم.'
    
    # =====================================
    # المدفوعات
    # =====================================
    
    @staticmethod
    def payment_amount_zero():
        return '⚠️ المبلغ يجب أن يكون أكبر من صفر.\n💡 أدخل المبلغ المدفوع فعلياً.'
    
    @staticmethod
    def payment_exceeds_due(amount, due):
        return (f'⚠️ المبلغ المدفوع ({amount:.2f}) أكبر من المستحق ({due:.2f})!\n'
                f'💡 المبلغ المستحق هو {due:.2f} درهم فقط.')
    
    @staticmethod
    def payment_method_required():
        return '⚠️ يجب اختيار طريقة الدفع.\n💡 اختر: نقدي، بطاقة، تحويل بنكي، أو شيك.'
    
    @staticmethod
    def cheque_number_required():
        return '⚠️ رقم الشيك مطلوب عند الدفع بشيك.\n💡 أدخل رقم الشيك وتاريخ الاستحقاق.'
    
    @staticmethod
    def reference_required():
        return '⚠️ الرقم المرجعي مطلوب للتحويل البنكي.\n💡 أدخل رقم الحوالة أو المعاملة.'
    
    # =====================================
    # المخزون
    # =====================================
    
    @staticmethod
    def warehouse_not_found():
        return '⚠️ المستودع غير موجود.\n💡 تأكد من اختيار مستودع صحيح من القائمة.'
    
    @staticmethod
    def stock_adjustment_invalid():
        return '⚠️ نوع التعديل غير صحيح.\n💡 اختر: إضافة، طرح، أو ضبط الكمية.'
    
    # =====================================
    # الصلاحيات
    # =====================================
    
    @staticmethod
    def permission_denied(action):
        return f'🚫 ليس لديك صلاحية للقيام بـ "{action}".\n💡 اتصل بالمدير لطلب الصلاحية.'
    
    @staticmethod
    def owner_only():
        return '👑 هذه الصفحة للمالك فقط.\n💡 فقط مالك النظام يمكنه الوصول لهذه الميزة.'
    
    @staticmethod
    def admin_only():
        return '🔐 هذه الصفحة للمديرين فقط.\n💡 يجب أن تكون مدير أو أعلى للوصول.'
    
    # =====================================
    # الملفات
    # =====================================
    
    @staticmethod
    def file_type_not_allowed(allowed_types):
        types_str = ', '.join(allowed_types)
        return (f'⚠️ نوع الملف غير مسموح.\n'
                f'💡 الأنواع المسموحة: {types_str}')
    
    @staticmethod
    def file_too_large(max_size_mb=5):
        return (f'⚠️ حجم الملف كبير جداً.\n'
                f'💡 الحد الأقصى: {max_size_mb}MB\n'
                f'💡 قم بضغط الملف أو اختر ملف أصغر.')
    
    @staticmethod
    def file_upload_failed(error):
        return f'❌ فشل رفع الملف.\n📝 السبب: {error}\n💡 تأكد من الملف وحاول مرة أخرى.'
    
    # =====================================
    # قاعدة البيانات
    # =====================================
    
    @staticmethod
    def database_error(error):
        return (f'❌ خطأ في قاعدة البيانات.\n'
                f'💡 السبب: {error}\n'
                f'💡 إذا استمرت المشكلة، اتصل بالدعم الفني.')
    
    @staticmethod
    def record_not_found(entity_type):
        entities = {
            'customer': 'العميل',
            'product': 'المنتج',
            'sale': 'الفاتورة',
            'user': 'المستخدم'
        }
        entity_ar = entities.get(entity_type, entity_type)
        return f'⚠️ {entity_ar} غير موجود.\n💡 قد يكون تم حذفه. تحقق من القائمة.'
    
    @staticmethod
    def duplicate_entry(field, value):
        return (f'⚠️ القيمة "{value}" موجودة مسبقاً في حقل "{field}".\n'
                f'💡 كل قيمة يجب أن تكون فريدة. جرب قيمة مختلفة.')
    
    # =====================================
    # التحقق من البيانات
    # =====================================
    
    @staticmethod
    def invalid_email():
        return '📧 البريد الإلكتروني غير صحيح.\n💡 الصيغة الصحيحة: name@example.com'
    
    @staticmethod
    def invalid_phone():
        return '📱 رقم الهاتف غير صحيح.\n💡 أمثلة: 0501234567 أو +971501234567'
    
    @staticmethod
    def invalid_number(field):
        return f'⚠️ القيمة في "{field}" يجب أن تكون رقماً.\n💡 أدخل رقم صحيح مثل: 100 أو 99.50'
    
    @staticmethod
    def invalid_date():
        return '⚠️ التاريخ غير صحيح.\n💡 الصيغة الصحيحة: YYYY-MM-DD مثل: 2025-10-28'
    
    @staticmethod
    def invalid_currency():
        return '⚠️ العملة غير صحيحة.\n💡 اختر من: AED, USD, EUR, SAR, KWD'
    
    # =====================================
    # النسخ الاحتياطي
    # =====================================
    
    @staticmethod
    def backup_wrong_password():
        return '🔒 كلمة المرور غير صحيحة!\n💡 أدخل كلمة مرور المالك الصحيحة.'
    
    @staticmethod
    def backup_corrupted():
        return '❌ النسخة الاحتياطية تالفة أو غير صالحة!\n💡 تأكد من الملف أو جرب نسخة احتياطية أخرى.'
    
    @staticmethod
    def backup_not_found():
        return '⚠️ النسخة الاحتياطية غير موجودة.\n💡 قد تكون تم حذفها. تحقق من القائمة.'
    
    @staticmethod
    def backup_failed(reason):
        return (f'❌ فشل إنشاء النسخة الاحتياطية.\n'
                f'📝 السبب: {reason}\n'
                f'💡 تأكد من مساحة القرص وصلاحيات الكتابة.')
    
    # =====================================
    # عام
    # =====================================
    
    @staticmethod
    def rate_limit_exceeded():
        return '⏱️ تجاوزت الحد المسموح من الطلبات.\n💡 انتظر دقيقة واحدة ثم حاول مرة أخرى.'
    
    @staticmethod
    def session_expired():
        return '⏱️ انتهت الجلسة بسبب عدم النشاط (30 دقيقة).\n💡 سجل الدخول مرة أخرى للمتابعة.'
    
    @staticmethod
    def csrf_error():
        return '🔒 خطأ في التحقق الأمني (CSRF).\n💡 قد تكون الجلسة انتهت. حدث الصفحة وحاول مرة أخرى.'
    
    @staticmethod
    def unexpected_error(error_id):
        return (f'❌ حدث خطأ غير متوقع.\n'
                f'🆔 معرف الخطأ: {error_id}\n'
                f'💡 تم تسجيل المشكلة. احتفظ بمعرف الخطأ عند التواصل مع الدعم.\n'
                f'💡 جرب إعادة تحميل الصفحة أو تسجيل الدخول مرة أخرى.')
    
    @staticmethod
    def required_field(field_name):
        return f'⚠️ حقل "{field_name}" مطلوب.\n💡 لا يمكن تركه فارغاً.'
    
    @staticmethod
    def invalid_format(field_name, example):
        return f'⚠️ صيغة "{field_name}" غير صحيحة.\n💡 مثال: {example}'
    
    # =====================================
    # رسائل النجاح (للمقارنة)
    # =====================================
    
    @staticmethod
    def success_create(entity_type):
        entities = {
            'customer': 'العميل',
            'product': 'المنتج',
            'sale': 'الفاتورة',
            'user': 'المستخدم',
            'payment': 'السند',
            'expense': 'المصروف'
        }
        entity_ar = entities.get(entity_type, entity_type)
        return f'✅ تم إضافة {entity_ar} بنجاح!'
    
    @staticmethod
    def success_update(entity_type):
        entities = {
            'customer': 'العميل',
            'product': 'المنتج',
            'sale': 'الفاتورة',
            'user': 'المستخدم'
        }
        entity_ar = entities.get(entity_type, entity_type)
        return f'✅ تم تحديث بيانات {entity_ar} بنجاح!'
    
    @staticmethod
    def success_delete(entity_type):
        entities = {
            'customer': 'العميل',
            'product': 'المنتج',
            'user': 'المستخدم'
        }
        entity_ar = entities.get(entity_type, entity_type)
        return f'✅ تم حذف {entity_ar} بنجاح!'


# دوال مساعدة سريعة
def error(msg):
    """رسالة خطأ مع أيقونة"""
    return f'❌ {msg}'

def warning(msg):
    """رسالة تحذير مع أيقونة"""
    return f'⚠️ {msg}'

def hint(msg):
    """رسالة مساعدة مع أيقونة"""
    return f'💡 {msg}'

def success(msg):
    """رسالة نجاح مع أيقونة"""
    return f'✅ {msg}'

