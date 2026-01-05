from app import create_app
from extensions import db
from models import Receipt, Payment, GLEntry, Cheque, Customer

app = create_app()
app.app_context().push()

# Get Bright Stars ID dynamically to be safe
bright_stars = Customer.query.filter(Customer.name.like('%النجوم الساطعة%')).first()
if not bright_stars:
    print("WARNING: Bright Stars customer not found! Using ID 1 as fallback.", flush=True)
    BRIGHT_STARS_ID = 1
else:
    BRIGHT_STARS_ID = bright_stars.id
    print(f"Found Bright Stars with ID: {BRIGHT_STARS_ID}", flush=True)

def clean_system():
    print("Starting cleanup...", flush=True)
    
    # 1. Clean Receipts
    receipts_to_delete = Receipt.query.filter(Receipt.customer_id != BRIGHT_STARS_ID).all()
    print(f"Found {len(receipts_to_delete)} receipts to delete.", flush=True)
    
    for r in receipts_to_delete:
        print(f"Deleting receipt {r.receipt_number}...", flush=True)
        # Delete associated GL Entries
        GLEntry.query.filter_by(reference_type='Receipt', reference_id=r.id).delete()
        # Delete associated Cheques
        Cheque.query.filter_by(receipt_record=r).delete()
        # Delete the receipt
        db.session.delete(r)
    
    # 2. Clean Payments
    payments_to_delete = Payment.query.filter(
        (Payment.customer_id != BRIGHT_STARS_ID) | (Payment.customer_id == None)
    ).all()
    print(f"Found {len(payments_to_delete)} payments to delete.", flush=True)
    
    for p in payments_to_delete:
        print(f"Deleting payment {p.payment_number}...", flush=True)
        # Delete associated GL Entries
        GLEntry.query.filter_by(reference_type='Payment', reference_id=p.id).delete()
        # Delete associated Cheques
        Cheque.query.filter_by(payment_record=p).delete()
        # Delete the payment
        db.session.delete(p)
        
    db.session.commit()
    print("Cleanup completed successfully.", flush=True)

if __name__ == "__main__":
    try:
        clean_system()
    except Exception as e:
        print(f"Error during cleanup: {e}", flush=True)
        db.session.rollback()
