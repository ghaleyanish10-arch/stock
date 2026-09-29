import asyncio
from app.nepse.registry import get_adapter

async def test():
    adapter = get_adapter()
    await adapter.start()
    
    print('=== get_press_releases (full) ===')
    try:
        result = await adapter.call('press_releases', lambda: adapter._client.get_press_releases())
        print(f'Type: {type(result)}')
        if isinstance(result, dict):
            print(f'Keys: {list(result.keys())}')
            for k, v in result.items():
                print(f'  {k}: {type(v)}')
                if isinstance(v, list):
                    print(f'  {k} count: {len(v)}')
                    if v:
                        print(f'  First: {v[0]}')
    except Exception as e:
        print(f'Error: {e}')
    
    print()
    print('=== get_top_gainers ===')
    try:
        result = await adapter.call('top_gainers', lambda: adapter._client.get_top_gainers(10))
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            if result:
                print(f'First: {result[0]}')
        else:
            print(f'Result: {result}')
    except Exception as e:
        print(f'Error: {e}')
    
    print()
    print('=== get_top_losers ===')
    try:
        result = await adapter.call('top_losers', lambda: adapter._client.get_top_losers(10))
        print(f'Type: {type(result)}')
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            if result:
                print(f'First: {result[0]}')
        else:
            print(f'Result: {result}')
    except Exception as e:
        print(f'Error: {e}')
    
    await adapter.close()

asyncio.run(test())