import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        for idx in ['nepse', 'banking', 'hydropower', 'finance', 'hotel']:
            resp = await client.get('http://127.0.0.1:8000/api/nepse/indices/{}/history?start=2026-08-01&end=2026-09-29'.format(idx))
            data = resp.json()
            if data.get('success'):
                history = data['data']['history']
                if history:
                    print('{}: {} points, first close={}, last close={}'.format(idx, len(history), history[0]['close'], history[-1]['close']))
                else:
                    print('{}: NO DATA'.format(idx))
            else:
                print('{}: ERROR'.format(idx))

asyncio.run(test())