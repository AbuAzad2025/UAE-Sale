with open(r'D:\recovers\data\UAE-Sale\services\aging_analysis_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = "if aging['total'] > 0:"
positions = []
start = 0
while True:
    pos = content.find(target, start)
    if pos == -1:
        break
    positions.append(pos)
    start = pos + 1

print(f'Found {len(positions)} occurrences at positions: {positions}')
for i, pos in enumerate(positions):
    print(f'  Occurrence {i+1}: ...{content[pos-50:pos+50]}...')