import os
for root, dirs, files in os.walk('D:/trading/data engine/app'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path) as fp:
                content = fp.read()
                if '@router.get("/")' in content or "@router.get('/')" in content:
                    print(path)