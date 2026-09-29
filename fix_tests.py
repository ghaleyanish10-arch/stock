with open('tests/test_reference_service.py', 'r') as f:
    content = f.read()

# Fix the test method calls
content = content.replace(
    'await svc.import_nav("NONEXISTENT", {"nav": 10.0, "nav_date": "2026-09-28", "source": "manual"}, s, None)',
    'await svc.import_nav(s, "NONEXISTENT", {"nav": 10.0, "nav_date": "2026-09-28", "source": "manual"})'
)
content = content.replace(
    'await svc.import_nav("TESTFUND", {"nav": "not-a-number", "nav_date": "2026-09-28", "source": "manual"}, s, None)',
    'await svc.import_nav(s, "TESTFUND", {"nav": "not-a-number", "nav_date": "2026-09-28", "source": "manual"})'
)
content = content.replace(
    'await svc.import_nav("TESTFUND", {"nav": 10.0, "nav_date": "invalid-date", "source": "manual"}, s, None)',
    'await svc.import_nav(s, "TESTFUND", {"nav": 10.0, "nav_date": "invalid-date", "source": "manual"})'
)
content = content.replace(
    'await svc.import_nav("TESTFUND", {"nav": -5.0, "nav_date": "2026-09-28", "source": "manual"}, s, None)',
    'await svc.import_nav(s, "TESTFUND", {"nav": -5.0, "nav_date": "2026-09-28", "source": "manual"})'
)
content = content.replace(
    'await svc.import_nav("TESTFUND", {"nav": 10.5, "nav_date": "2026-09-28", "source": "manual"}, s, None)',
    'await svc.import_nav(s, "TESTFUND", {"nav": 10.5, "nav_date": "2026-09-28", "source": "manual"})'
)
content = content.replace(
    'await svc.import_nav("TESTFUND", {"nav": 11.0, "nav_date": "2026-09-28", "source": "manual"}, s, None)',
    'await svc.import_nav(s, "TESTFUND", {"nav": 11.0, "nav_date": "2026-09-28", "source": "manual"})'
)

with open('tests/test_reference_service.py', 'w') as f:
    f.write(content)
print('Done')