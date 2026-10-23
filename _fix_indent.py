import re

with open(r'D:\recovers\data\UAE-Sale\services\aging_analysis_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the indentation error - find the malformed lines
# Look for the pattern where 'if aging' has wrong indentation
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'if aging' in line and '>' in line and '0:' in line:
        # Check if previous line has wrong indentation
        if i > 0 and lines[i-1].strip().startswith('aging'):
            # Fix the indentation
            lines[i] = '            if aging[\'total\'] > 0:'
            print(f'Fixed line {i+1}')
            break

with open(r'D:\recovers\data\UAE-Sale\services\aging_analysis_service.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print('Fixed indentation')