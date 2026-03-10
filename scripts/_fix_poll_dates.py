"""Fix poll entries that used UTC dates instead of Pacific."""
import json

with open('data/pocketcasts_history.json') as f:
    h = json.load(f)

fixed = 0
for k, v in h.items():
    if v.get('src') == 'poll' and v.get('d') == '2026-03-10':
        v['d'] = '2026-03-09'
        fixed += 1
        print(f"  Fixed: {v.get('p','')} -> 2026-03-09")

with open('data/pocketcasts_history.json', 'w') as f:
    json.dump(h, f, separators=(',',':'))
print(f'Fixed {fixed} entries')
