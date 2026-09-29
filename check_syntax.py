with open('seed_rates.py', 'r', encoding='utf-8') as f:
    content = f.read()

try:
    compile(content, 'seed_rates.py', 'exec')
    print('Full file compiles OK')
except SyntaxError as e:
    print(f'Syntax error: {e}')
    print(f'Line {e.lineno}: {e.text}')

# Test just the main block
main_code = '''
if __name__ == "__main__":
    main()
'''
try:
    compile(main_code, 'test', 'exec')
    print('Main block compiles OK')
except SyntaxError as e:
    print(f'Syntax error in main: {e}')