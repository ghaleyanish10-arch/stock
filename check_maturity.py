from app.db.session import SessionLocal
from app.db.models import Fund
import re
from datetime import datetime, timedelta

session = SessionLocal()
funds = session.query(Fund).filter(Fund.close_ended == True).all()
for f in funds:
    match = re.search(r'(\d+)\s*years?\s*maturity', f.scheme_description or '', re.IGNORECASE)
    if match:
        years = int(match.group(1))
        if f.listing_date:
            try:
                list_date = datetime.strptime(f.listing_date, '%Y-%m-%d')
                maturity = list_date + timedelta(days=years * 365)
                print(f'{f.code}: maturity={maturity.strftime("%Y-%m-%d")}, scheme={f.scheme_description}')
            except:
                pass
    # Also check for funds without maturity date
    if not f.maturity_date:
        print(f'{f.code}: NO maturity_date, scheme={f.scheme_description}')
session.close()