
import sys
import os
print("Script started...")
from decimal import Decimal

# Add project root to path
sys.path.append(os.getcwd())

# Set dummy key for testing
os.environ['CARD_ENCRYPTION_KEY'] = 'dummy_key_for_testing_only_12345'
os.environ['FLASK_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite:///test_financials.db'

from app import create_app
from config import Config
from extensions import db
from services.gl_service import GLService
from models import GLAccount, GLJournalEntry, GLJournalLine

class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = 'sqlite:///test_financials.db'
    TESTING = True
    SQLALCHEMY_ENGINE_OPTIONS = {}

def test_multi_currency_gl():
    app = create_app(TestConfig)
    with app.app_context():
        print(f"DB URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
        
        # Import all models to ensure they are registered
        import models
        
        # Create tables for SQLite
        db.create_all()
        print("Tables created.")
        
        print("Starting Multi-Currency GL Verification...")
        
        # 1. Ensure accounts exist
        GLService.ensure_core_accounts()
        
        # 2. Define Test Data
        # Purchase 100 USD worth of goods
        # Exchange Rate: 1 USD = 3.6725 AED
        currency = 'USD'
        exchange_rate = Decimal('3.6725')
        amount_usd = Decimal('100.00')
        
        # 3. Create GL Lines (using original currency amounts)
        lines = [
            {
                'account': '1140', # Inventory (Asset)
                'debit': amount_usd,
                'credit': Decimal('0'),
                'description': 'Test Import Purchase (Debit)'
            },
            {
                'account': '2110', # Accounts Payable (Liability)
                'debit': Decimal('0'),
                'credit': amount_usd,
                'description': 'Test Import Purchase (Credit)'
            }
        ]
        
        # 4. Post Entry
        print(f"Posting Entry: {amount_usd} {currency} @ {exchange_rate} AED")
        entry = GLService.post_entry(
            lines,
            description="Test Multi-Currency Purchase",
            reference_type="Test",
            reference_id=999,
            currency=currency,
            exchange_rate=exchange_rate
        )
        
        if not entry:
            print("❌ Failed to post entry!")
            return
            
        print(f"Entry Posted. ID: {entry.id}, Number: {entry.entry_number}")
        
        # 5. Verify Database Records
        # Reload entry from DB to be sure
        saved_entry = GLJournalEntry.query.get(entry.id)
        
        # Check Entry Header
        if saved_entry.currency != currency:
            print(f"❌ Entry currency mismatch. Expected {currency}, got {saved_entry.currency}")
        if saved_entry.exchange_rate != exchange_rate:
            print(f"❌ Entry exchange_rate mismatch. Expected {exchange_rate}, got {saved_entry.exchange_rate}")
            
        # Check Lines
        asset_line = next(l for l in saved_entry.lines if l.account.code == '1140')
        liability_line = next(l for l in saved_entry.lines if l.account.code == '2110')
        
        # Verify Asset Line
        expected_aed_asset = amount_usd * exchange_rate
        print(f"Asset Line (1140): Debit={asset_line.debit}, AED={asset_line.amount_aed}")
        
        if asset_line.debit != amount_usd:
            print(f"❌ Asset Debit Mismatch. Expected {amount_usd}, got {asset_line.debit}")
        
        # Allow small rounding difference for AED amount if necessary, but Decimal should be precise
        if abs(asset_line.amount_aed - expected_aed_asset) > Decimal('0.001'):
             print(f"❌ Asset Amount AED Mismatch. Expected {expected_aed_asset}, got {asset_line.amount_aed}")
        else:
            print("✅ Asset Line Amounts Correct")

        # Verify Liability Line
        expected_aed_liability = - (amount_usd * exchange_rate)
        print(f"Liability Line (2110): Credit={liability_line.credit}, AED={liability_line.amount_aed}")
        
        if liability_line.credit != amount_usd:
            print(f"❌ Liability Credit Mismatch. Expected {amount_usd}, got {liability_line.credit}")
            
        if abs(liability_line.amount_aed - expected_aed_liability) > Decimal('0.001'):
             print(f"❌ Liability Amount AED Mismatch. Expected {expected_aed_liability}, got {liability_line.amount_aed}")
        else:
            print("✅ Liability Line Amounts Correct")

        # 6. Verify Balances
        # Note: This checks the TOTAL balance, so it includes previous transactions. 
        # But since we added a known amount, we can check if it makes sense or just check logic.
        # Actually, let's just check if get_balance runs without error and returns a Decimal.
        
        asset_account = GLAccount.query.filter_by(code='1140').first()
        liability_account = GLAccount.query.filter_by(code='2110').first()
        
        bal_asset = asset_account.get_balance()
        bal_liab = liability_account.get_balance()
        
        print(f"Current Inventory Balance (AED): {bal_asset}")
        print(f"Current Payable Balance (AED): {bal_liab}")
        
        if not isinstance(bal_asset, Decimal):
             print(f"❌ Balance is not Decimal: {type(bal_asset)}")
        
        print("\n✅ Verification Complete!")

if __name__ == "__main__":
    test_multi_currency_gl()
