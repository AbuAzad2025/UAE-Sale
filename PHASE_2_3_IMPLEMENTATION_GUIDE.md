# 📊 دليل تنفيذ المرحلة الثانية والثالثة

## ✅ **ما تم إنجازه حتى الآن:**

### **المرحلة الأولى (100%):** ✅
- ✅ شجرة الحسابات (50+ حساب)
- ✅ القيود اليومية المحسّنة
- ✅ كشف الحساب التفصيلي
- ✅ ربط الشيكات بدفتر الأستاذ
- ✅ Templates كاملة
- ✅ Migration مطبّق
- ✅ 50 حساب محاسبي جاهز

### **المرحلة الثانية (بدأت):**
- ✅ **Models**: `BankReconciliation`, `BankReconciliationItem`
- ✅ **Service**: `BankReconciliationService` مع دوال كاملة
- ⏳ **Routes**: يحتاج إنشاء
- ⏳ **Templates**: يحتاج إنشاء

---

## 🚀 **خطوات الإكمال المتبقية:**

### **1. إكمال المرحلة الثانية:**

#### أ. Routes مطابقة البنك:
```python
# routes/bank_reconciliation.py

@bank_recon_bp.route('/')
def index():
    """قائمة المطابقات"""

@bank_recon_bp.route('/create', methods=['GET', 'POST'])
def create():
    """إنشاء مطابقة جديدة"""

@bank_recon_bp.route('/<int:id>')
def view(id):
    """عرض تفاصيل المطابقة"""

@bank_recon_bp.route('/<int:id>/add-charge', methods=['POST'])
def add_charge(id):
    """إضافة مصروف بنكي"""

@bank_recon_bp.route('/<int:id>/add-interest', methods=['POST'])
def add_interest(id):
    """إضافة فائدة بنكية"""

@bank_recon_bp.route('/<int:id>/complete', methods=['POST'])
def complete(id):
    """إكمال المطابقة"""

@bank_recon_bp.route('/<int:id>/approve', methods=['POST'])
def approve(id):
    """اعتماد المطابقة"""
```

#### ب. Templates مطابقة البنك:
- `templates/bank_reconciliation/index.html` - قائمة المطابقات
- `templates/bank_reconciliation/create.html` - نموذج إنشاء
- `templates/bank_reconciliation/view.html` - عرض التفاصيل
- `templates/bank_reconciliation/summary.html` - ملخص المطابقة

---

#### ج. قائمة التدفقات النقدية (Cash Flow Statement):

**Service:**
```python
# services/cash_flow_service.py

class CashFlowService:
    @staticmethod
    def generate_cash_flow(period_start, period_end):
        """
        إنشاء قائمة التدفقات النقدية
        
        Returns:
            {
                'operating_activities': [...],
                'investing_activities': [...],
                'financing_activities': [...],
                'net_change_in_cash': float,
                'cash_beginning': float,
                'cash_ending': float
            }
        """
        # 1. الأنشطة التشغيلية
        operating = {
            'receipts_from_customers': 0,  # مقبوضات من عملاء
            'payments_to_suppliers': 0,     # مدفوعات لموردين
            'payments_for_expenses': 0,     # مدفوعات مصروفات
            'payments_for_salaries': 0      # مدفوعات رواتب
        }
        
        # 2. الأنشطة الاستثمارية
        investing = {
            'purchase_of_fixed_assets': 0,  # شراء أصول ثابتة
            'sale_of_fixed_assets': 0       # بيع أصول ثابتة
        }
        
        # 3. الأنشطة التمويلية
        financing = {
            'owner_contributions': 0,       # إضافات رأس المال
            'owner_withdrawals': 0,         # سحوبات المالك
            'loans_received': 0,            # قروض مستلمة
            'loan_repayments': 0            # سداد قروض
        }
```

**Route:**
```python
@ledger_bp.route('/cash-flow')
def cash_flow():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    report = CashFlowService.generate_cash_flow(date_from, date_to)
    
    return render_template('ledger/cash_flow.html', report=report)
```

---

#### د. تحليل العمر (Aging Analysis):

**Service:**
```python
# services/aging_analysis_service.py

class AgingAnalysisService:
    @staticmethod
    def get_receivables_aging():
        """
        تحليل عمر الذمم المدينة
        
        Returns:
            {
                'customers': [
                    {
                        'customer': Customer object,
                        '0-30': Decimal,
                        '31-60': Decimal,
                        '61-90': Decimal,
                        '91-120': Decimal,
                        'over_120': Decimal,
                        'total': Decimal
                    }
                ],
                'totals': {...}
            }
        """
        from models import Customer, Sale
        from datetime import date, timedelta
        
        today = date.today()
        results = []
        
        customers = Customer.query.filter_by(is_active=True).all()
        
        for customer in customers:
            aging = {
                'customer': customer,
                '0-30': Decimal('0'),
                '31-60': Decimal('0'),
                '61-90': Decimal('0'),
                '91-120': Decimal('0'),
                'over_120': Decimal('0'),
                'total': Decimal('0')
            }
            
            # المبيعات غير المدفوعة
            unpaid_sales = Sale.query.filter(
                Sale.customer_id == customer.id,
                Sale.payment_status != 'paid'
            ).all()
            
            for sale in unpaid_sales:
                days_old = (today - sale.sale_date.date()).days
                balance = sale.total_amount - sale.paid_amount
                
                if days_old <= 30:
                    aging['0-30'] += balance
                elif days_old <= 60:
                    aging['31-60'] += balance
                elif days_old <= 90:
                    aging['61-90'] += balance
                elif days_old <= 120:
                    aging['91-120'] += balance
                else:
                    aging['over_120'] += balance
                
                aging['total'] += balance
            
            if aging['total'] > 0:
                results.append(aging)
        
        return results
    
    @staticmethod
    def get_payables_aging():
        """تحليل عمر الذمم الدائنة (للموردين)"""
        # نفس الفكرة للموردين
```

**Route:**
```python
@ledger_bp.route('/aging-analysis')
def aging_analysis():
    analysis_type = request.args.get('type', 'receivables')  # receivables or payables
    
    if analysis_type == 'receivables':
        report = AgingAnalysisService.get_receivables_aging()
    else:
        report = AgingAnalysisService.get_payables_aging()
    
    return render_template('ledger/aging_analysis.html', 
                         report=report, 
                         analysis_type=analysis_type)
```

---

### **2. المرحلة الثالثة:**

#### أ. الموازنة التخطيطية (Budgeting):

**Model:**
```python
class Budget(db.Model):
    __tablename__ = 'budgets'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_number = db.Column(db.String(50), unique=True)
    fiscal_year = db.Column(db.Integer, nullable=False)  # 2025, 2026
    period_type = db.Column(db.String(20), default='annual')  # annual, quarterly, monthly
    status = db.Column(db.String(20), default='draft')
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime)
    approved_at = db.Column(db.DateTime)
    
    lines = db.relationship('BudgetLine', back_populates='budget')


class BudgetLine(db.Model):
    __tablename__ = 'budget_lines'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'))
    account_id = db.Column(db.Integer, db.ForeignKey('gl_accounts.id'))
    
    # المبالغ المخططة
    budgeted_amount = db.Column(db.Numeric(18, 3), nullable=False)
    
    # المبالغ الفعلية (محسوبة)
    actual_amount = db.Column(db.Numeric(18, 3), default=0)
    
    # الانحراف
    variance = db.Column(db.Numeric(18, 3), default=0)
    variance_percentage = db.Column(db.Numeric(5, 2), default=0)
    
    budget = db.relationship('Budget', back_populates='lines')
    account = db.relationship('GLAccount')
```

---

#### ب. مراكز التكلفة (Cost Centers):

**Model:**
```python
class CostCenter(db.Model):
    __tablename__ = 'cost_centers'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name_ar = db.Column(db.String(200), nullable=False)
    name_en = db.Column(db.String(200))
    parent_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'))
    
    is_active = db.Column(db.Boolean, default=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    parent = db.relationship('CostCenter', remote_side=[id], backref='children')
    manager = db.relationship('User')
```

**ربط مع القيود:**
```python
# في GLJournalLine
cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'))
cost_center = db.relationship('CostCenter')
```

---

#### ج. الأصول الثابتة والاستهلاك (Fixed Assets):

**Model:**
```python
class FixedAsset(db.Model):
    __tablename__ = 'fixed_assets'
    
    id = db.Column(db.Integer, primary_key=True)
    asset_number = db.Column(db.String(50), unique=True)
    name_ar = db.Column(db.String(200), nullable=False)
    name_en = db.Column(db.String(200))
    
    # الحسابات
    asset_account_id = db.Column(db.Integer, db.ForeignKey('gl_accounts.id'))  # الأصل
    depreciation_account_id = db.Column(db.Integer, db.ForeignKey('gl_accounts.id'))  # مجمع الاستهلاك
    expense_account_id = db.Column(db.Integer, db.ForeignKey('gl_accounts.id'))  # مصروف الاستهلاك
    
    # التكلفة
    purchase_date = db.Column(db.Date, nullable=False)
    purchase_price = db.Column(db.Numeric(18, 3), nullable=False)
    salvage_value = db.Column(db.Numeric(18, 3), default=0)  # القيمة الإنقاذية
    
    # الاستهلاك
    depreciation_method = db.Column(db.String(30), default='straight_line')  # straight_line, declining_balance
    useful_life_years = db.Column(db.Integer, nullable=False)  # العمر الإنتاجي
    useful_life_months = db.Column(db.Integer)
    
    # القيم المحسوبة
    accumulated_depreciation = db.Column(db.Numeric(18, 3), default=0)
    book_value = db.Column(db.Numeric(18, 3))
    
    status = db.Column(db.String(20), default='active')  # active, disposed, fully_depreciated
    
    depreciation_schedules = db.relationship('DepreciationSchedule', back_populates='asset')


class DepreciationSchedule(db.Model):
    __tablename__ = 'depreciation_schedules'
    
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('fixed_assets.id'))
    
    period_date = db.Column(db.Date, nullable=False)  # نهاية الشهر/السنة
    depreciation_amount = db.Column(db.Numeric(18, 3), nullable=False)
    accumulated_depreciation = db.Column(db.Numeric(18, 3))
    book_value = db.Column(db.Numeric(18, 3))
    
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('gl_journal_entries.id'))
    
    asset = db.relationship('FixedAsset', back_populates='depreciation_schedules')
    journal_entry = db.relationship('GLJournalEntry')
```

**Service:**
```python
class DepreciationService:
    @staticmethod
    def calculate_monthly_depreciation(asset):
        """حساب الاستهلاك الشهري"""
        if asset.depreciation_method == 'straight_line':
            depreciable_amount = asset.purchase_price - asset.salvage_value
            months = asset.useful_life_years * 12
            monthly_depreciation = depreciable_amount / months
            return monthly_depreciation
        
        elif asset.depreciation_method == 'declining_balance':
            rate = 2 / asset.useful_life_years  # معدل القسط المتناقص المضاعف
            current_book_value = asset.book_value or asset.purchase_price
            monthly_depreciation = (current_book_value * rate) / 12
            return monthly_depreciation
    
    @staticmethod
    def post_monthly_depreciation():
        """ترحيل الاستهلاك الشهري لجميع الأصول"""
        from models import FixedAsset
        from services.gl_service import GLService
        from datetime import date
        
        today = date.today()
        
        active_assets = FixedAsset.query.filter_by(status='active').all()
        
        for asset in active_assets:
            depreciation = DepreciationService.calculate_monthly_depreciation(asset)
            
            if depreciation > 0:
                # إنشاء قيد الاستهلاك
                lines = [
                    {
                        'account': str(asset.expense_account.code),
                        'debit': depreciation,
                        'credit': 0,
                        'description': f'استهلاك {asset.name_ar}'
                    },
                    {
                        'account': str(asset.depreciation_account.code),
                        'debit': 0,
                        'credit': depreciation,
                        'description': f'مجمع استهلاك {asset.name_ar}'
                    }
                ]
                
                entry = GLService.post_entry(
                    lines=lines,
                    description=f'قيد استهلاك شهري - {asset.name_ar}',
                    reference_type='depreciation',
                    reference_id=asset.id
                )
                
                # تسجيل في جدول الاستهلاك
                schedule = DepreciationSchedule(
                    asset_id=asset.id,
                    period_date=today,
                    depreciation_amount=depreciation,
                    accumulated_depreciation=asset.accumulated_depreciation + depreciation,
                    book_value=asset.book_value - depreciation,
                    journal_entry_id=entry.id
                )
                db.session.add(schedule)
                
                # تحديث الأصل
                asset.accumulated_depreciation += depreciation
                asset.book_value -= depreciation
                
                if asset.book_value <= asset.salvage_value:
                    asset.status = 'fully_depreciated'
        
        db.session.commit()
```

---

## 📊 **Migration Scripts المطلوبة:**

### 1. Bank Reconciliation:
```python
# database_migrations/migrate_bank_reconciliation.py
# إنشاء جداول: bank_reconciliations, bank_reconciliation_items
```

### 2. Budget:
```python
# database_migrations/migrate_budget.py
# إنشاء جداول: budgets, budget_lines
```

### 3. Cost Centers:
```python
# database_migrations/migrate_cost_centers.py
# إنشاء جدول: cost_centers
# إضافة cost_center_id لـ gl_journal_lines
```

### 4. Fixed Assets:
```python
# database_migrations/migrate_fixed_assets.py
# إنشاء جداول: fixed_assets, depreciation_schedules
```

---

## 🎯 **أولويات التنفيذ:**

1. **عالية جداً** 🔴:
   - ✅ مطابقة البنك (Models ✅ + Service ✅ + Routes + Templates)
   - قائمة التدفقات النقدية
   - تحليل العمر

2. **متوسطة** 🟡:
   - الموازنة التخطيطية
   - مراكز التكلفة

3. **عادية** 🟢:
   - الأصول الثابتة والاستهلاك (نظام كامل)

---

## ✅ **الملخص:**

**ما تم:**
- ✅ المرحلة الأولى كاملة (100%)
- ✅ Models + Service لمطابقة البنك (60%)

**المتبقي:**
- Routes + Templates لمطابقة البنك
- قائمة التدفقات النقدية (كاملة)
- تحليل العمر (كامل)
- المرحلة الثالثة (3 أنظمة)

**الوقت المتوقع:**
- إكمال المرحلة الثانية: 4-6 ساعات
- المرحلة الثالثة: 8-10 ساعات

---

**هل تريد الاستمرار في نفس الجلسة أم تأخذ استراحة؟** 💪

