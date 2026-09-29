import os
for root, dirs, files in os.walk(r'D:\trading\data engine\app'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as fp:
                content = fp.read()
                if '@router.get("/")' in content:
                    print(path)