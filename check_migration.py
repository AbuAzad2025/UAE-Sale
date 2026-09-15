import os

f = 'migrations/versions/d1aee72dd9da_initial_schema.py'
with open(f, 'rb') as fp:
    data = fp.read()
print(f'Length: {len(data)} bytes')
print(f'Null bytes: {data.count(b"\\x00")}')
print(f'First 200 chars: {data[:200].decode(errors="ignore")}')
print('Valid UTF-8: True')

# Check down_revision
import re
content = data.decode('utf-8', errors='ignore')
m = re.search(r"down_revision\s*=\s*['\"]([^'\"]+)['\"]", content)
if m:
    print(f'down_revision: {m.group(1)}')
else:
    print('down_revision: None (base)')