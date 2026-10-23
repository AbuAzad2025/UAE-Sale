with open(r'D:\recovers\data\UAE-Sale\services\aging_analysis_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Insert the fix before the second occurrence
target = "            if aging['total'] > 0:"
pos = content.find(target, 8193)  # Second occurrence

if pos != -1:
    # Insert the fix before this line
    prefix = content[:pos]
    suffix = content[pos:]
    # Insert the fix with proper indentation (12 spaces)
    fix = "            aging['total'] = supplier_balance\n            "
    new_content = content[:pos] + fix + content[pos:]
    
    with open(r'D:\recovers\data\UAE-Sale\services\aging_analysis_service.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Fixed!')
else:
    print('Position not found')