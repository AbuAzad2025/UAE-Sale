from decimal import Decimal
from datetime import datetime, timezone
from extensions import db
from models import GLAccount, GLJournalEntry, GLJournalLine
from utils.helpers import generate_number


class GLService:
    @staticmethod
    def ensure_core_accounts():
        """Create core GL accounts with both Arabic and English names"""
        core = [
            ('1000', 'الصندوق', 'Cash', 'asset'),
            ('1010', 'البنك', 'Bank', 'asset'),
            ('1100', 'الذمم المدينة', 'Accounts Receivable', 'asset'),
            ('1200', 'المخزون', 'Inventory', 'asset'),
            ('2000', 'الذمم الدائنة', 'Accounts Payable', 'liability'),
            ('2100', 'ضرائب مستحقة', 'Taxes Payable', 'liability'),
            ('3000', 'حقوق الملكية', 'Equity', 'equity'),
            ('4000', 'المبيعات', 'Sales Revenue', 'revenue'),
            ('4100', 'إيرادات الشحن', 'Shipping Revenue', 'revenue'),
            ('5000', 'تكلفة المبيعات', 'Cost of Sales', 'expense'),
            ('5100', 'مصروفات الشحن', 'Shipping Expense', 'expense'),
            ('5200', 'الخصومات', 'Discounts', 'expense'),
            ('6000', 'المصروفات العمومية', 'General Expenses', 'expense'),
            ('6100', 'رواتب', 'Salaries', 'expense'),
            ('6200', 'إيجار', 'Rent', 'expense'),
            ('6300', 'كهرباء وماء', 'Utilities', 'expense'),
            ('6400', 'صيانة', 'Maintenance', 'expense'),
            ('6500', 'تسويق', 'Marketing', 'expense'),
            ('6600', 'مواصلات', 'Transportation', 'expense'),
        ]
        for code, name_ar, name_en, t in core:
            acc = GLAccount.query.filter_by(code=code).first()
            if not acc:
                db.session.add(GLAccount(
                    code=code,
                    name=name_en,  # English name as primary
                    name_ar=name_ar,  # Arabic name
                    type=t,
                    currency='AED'
                ))
        db.session.commit()
    
    @staticmethod
    def create_journal_entry(entry_type, description, lines, reference_type=None, reference_id=None):
        """
        Create a journal entry
        
        Args:
            entry_type (str): Type of entry (sale, purchase, payment, etc.)
            description (str): Entry description
            lines (list): List of journal lines [{'account_code': str, 'debit': Decimal, 'credit': Decimal}]
            reference_type (str): Optional reference type
            reference_id (int): Optional reference ID
        
        Returns:
            GLJournalEntry: Created journal entry
        
        Raises:
            ValueError: If entry is not balanced
        """
        from models import GLAccount, GLJournalEntry, GLJournalLine
        
        # Validate balance
        total_debit = sum(Decimal(str(line['debit'])) for line in lines)
        total_credit = sum(Decimal(str(line['credit'])) for line in lines)
        
        if total_debit != total_credit:
            raise ValueError(f"Journal entry is not balanced: Debit={total_debit}, Credit={total_credit}")
        
        # Generate entry number
        entry_number = generate_number('JE', GLJournalEntry, 'entry_number')
        
        # Create entry
        entry = GLJournalEntry(
            entry_number=entry_number,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            total_debit=total_debit,
            total_credit=total_credit
        )
        db.session.add(entry)
        db.session.flush()
        
        # Create lines
        for line_data in lines:
            account = GLAccount.query.filter_by(code=line_data['account_code']).first()
            if not account:
                raise ValueError(f"Account {line_data['account_code']} not found")
            
            line = GLJournalLine(
                entry_id=entry.id,
                account_id=account.id,
                debit=Decimal(str(line_data['debit'])),
                credit=Decimal(str(line_data['credit'])),
                description=line_data.get('description', description)
            )
            db.session.add(line)
        
        db.session.commit()
        return entry

    @staticmethod
    def post_entry(lines, description='', reference_type=None, reference_id=None, currency='AED', exchange_rate=1):
        entry_number = generate_number('JE', GLJournalEntry, 'entry_number')
        entry = GLJournalEntry(
            entry_number=entry_number,
            entry_date=datetime.now(timezone.utc),
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            currency=currency,
            exchange_rate=Decimal(str(exchange_rate))
        )
        db.session.add(entry)
        total_debit = Decimal('0')
        total_credit = Decimal('0')
        for ln in lines:
            account = ln['account'] if isinstance(ln['account'], GLAccount) else GLAccount.query.filter_by(code=ln['account']).first()
            debit = Decimal(str(ln.get('debit', 0) or 0))
            credit = Decimal(str(ln.get('credit', 0) or 0))
            amount_aed = (debit - credit) * Decimal(str(exchange_rate))
            db.session.add(GLJournalLine(
                entry=entry,
                account=account,
                description=ln.get('description'),
                debit=debit,
                credit=credit,
                amount_aed=amount_aed
            ))
            total_debit += debit
            total_credit += credit
        entry.total_debit = total_debit
        entry.total_credit = total_credit
        if total_debit != total_credit:
            raise ValueError('GL entry not balanced')
        db.session.flush()
        return entry


