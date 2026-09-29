"""Probe all unused nepse-data-api methods live."""

import asyncio
from datetime import date, timedelta
from app.nepse.registry import get_adapter
from app.db.session import SessionLocal
from app.db.models import Security

async def probe():
    adapter = get_adapter()
    await adapter.start()
    
    print("=== 1. get_all_indices (sub-indices) ===")
    try:
        result = await adapter.call('sub_indices', lambda: adapter.get_sub_indices())
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:5]:
                print(f'  {item}')
        else:
            print(f'  {result}')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 2. get_top_turnover ===")
    try:
        result = await adapter.call('top_turnover', lambda: adapter.get_top_turnover())
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:5]:
                print(f'  {item}')
        else:
            print(f'  {result}')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 3. get_top_trade ===")
    try:
        result = await adapter.call('top_trade', lambda: adapter.get_top_trade())
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:5]:
                print(f'  {item}')
        else:
            print(f'  {result}')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 4. get_top_transaction ===")
    try:
        result = await adapter.call('top_transaction', lambda: adapter.get_top_transaction())
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:5]:
                print(f'  {item}')
        else:
            print(f'  {result}')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 5. get_floorsheet (NABIL) ===")
    try:
        session = SessionLocal()
        security = SessionLocal().query(Security).filter(Security.symbol == 'NABIL').first()
        SessionLocal().close()
        if security and security.nepse_security_id:
            result = await adapter.call(f'floorsheet:{security.nepse_security_id}', lambda: adapter.get_floorsheet(security.nepse_security_id))
            print(f'Type: {type(result)}')
            if isinstance(result, list):
                print(f'Count: {len(result)}')
                for item in result[:5]:
                    print(f'  {item}')
            else:
                print(f'  {result}')
        else:
            print('NABIL not found or no security ID')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 6. get_daily_trade (today) ===")
    try:
        today = date.today()
        result = await adapter.call(f'daily_trade:{today}', lambda: adapter.get_daily_trade(date.today()))
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:5]:
                print(f'  {item}')
        else:
            print(f'  {result}')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 7. get_daily_trade (yesterday) ===")
    try:
        yesterday = date.today() - timedelta(days=1)
        result = await adapter.call(f'daily_trade:{yesterday}', lambda: adapter.get_daily_trade(date.today() - timedelta(days=1)))
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:5]:
                print(f'  {item}')
        else:
            print(f'  {result}')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 8. get_press_releases ===")
    try:
        result = await adapter.call('press_releases', lambda: adapter.get_press_releases())
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:5]:
                print(f'  {item}')
        else:
            print(f'  {result}')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 9. get_company_news (NABIL) ===")
    try:
        session = SessionLocal()
        security = SessionLocal().query(Security).filter(Security.symbol == 'NABIL').first()
        SessionLocal().close()
        if security and security.nepse_security_id:
            result = await adapter.call(f'company_news:{security.nepse_security_id}', lambda: adapter.get_company_news(security.nepse_security_id))
            print(f'Type: {type(result)}')
            if isinstance(result, list):
                print(f'Count: {len(result)}')
                for item in result[:3]:
                    print(f'  {item}')
            else:
                print(f'  {result}')
        else:
            print('NABIL not found')
    except Exception as e:
        print(f'Error: {e}')

    print()
    print("=== 10. get_news_alerts ===")
    try:
        result = await adapter.call('news_alerts', lambda: adapter.get_news_alerts())
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:3]:
                print(f'  {item}')
        else:
            print(f'  {result}')
    except Exception as e:
        print(f'Error: {e}')

    await adapter.close()

if __name__ == "__main__":
    asyncio.run(probe())