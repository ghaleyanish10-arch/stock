from app.reference.service import ReferenceService
from app.nepse.registry import get_adapter
from app.db.session import SessionLocal
import asyncio

async def re_enrich_all():
    adapter = get_adapter()
    await adapter.start()
    svc = ReferenceService(adapter)
    session = SessionLocal()
    try:
        from app.db.models import Fund
        funds = session.query(Fund).filter(Fund.close_ended == True).all()
        print(f'Found {len(funds)} close-ended funds to re-enrich')
        for f in funds:
            try:
                print(f'Enriching {f.code}...')
                result = await svc.enrich_security(session, f.code)
                print(f'  maturity_date: {result.get("maturity_date", "NOT SET")}')
            except Exception as e:
                print(f'  Error: {e}')
                session.rollback()
    finally:
        session.close()
        await adapter.close()

asyncio.run(re_enrich_all())