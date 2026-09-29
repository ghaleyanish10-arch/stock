import asyncio
from app.nepse.registry import get_adapter

async def test():
    adapter = get_adapter()
    await adapter.start()
    try:
        result = await adapter.call('company_news:131', lambda: adapter.get_json('application/company-news/131'))
        if isinstance(result, list):
            print(f'Count: {len(result)}')
            for item in result[:3]:
                print(f'  Item keys: {list(item.keys())}')
                if 'companyNews' in item:
                    cn = item['companyNews']
                    print(f'  companyNews keys: {list(cn.keys())}')
                    print(f'  headline: {cn.get("newsHeadline")}')
                    print(f'  newsType: {cn.get("newsType")}')
                    print(f'  newsSource: {cn.get("newsSource")}')
                    print(f'  addedDate: {cn.get("addedDate")}')
                    body = cn.get("newsBody", "")
                    print(f'  newsBody: {body[:100]}...')
    except Exception as e:
        print(f'Error: {e}')
    await adapter.close()

asyncio.run(test())