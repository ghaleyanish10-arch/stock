from app.db.session import SessionLocal
from app.db.models import Fund, Security

session = SessionLocal()

# Check C30MF's security_type
sec = session.query(Security).filter(Security.symbol == 'C30MF').first()
print(f'C30MF security_type: {sec.security_type if sec else "NOT FOUND"}')

# Check all funds' security_type
funds = session.query(Fund).all()
for f in funds:
    sec = session.query(Security).filter(Security.symbol == f.code).first()
    if sec and sec.security_type != 'CDS':
        print(f'{f.code}: security_type={sec.security_type}')

session.close()