import json, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open('data/letterboxd.json') as f:
    lb = json.load(f)
cache = {}
if os.path.exists('data/lb_slug_cache.json'):
    with open('data/lb_slug_cache.json') as f:
        cache = json.load(f)

# 2022 Letterboxd movies
lb_2022 = []
for k, v in lb.items():
    for d in v.get('dates', []):
        if d[:4] == '2022':
            lb_2022.append({'title': v['title'], 'year': str(v.get('year','')), 'date': d})
            break

print(f"Letterboxd 2022 watches: {len(lb_2022)}")

resolved = 0
unresolved = []
for m in lb_2022:
    key = m['title'] + '|' + m['year']
    slug = cache.get(key, '')
    if slug:
        resolved += 1
    else:
        unresolved.append(m['title'] + ' (' + m['year'] + ')')

print(f"With Trakt slug: {resolved}")
print(f"Missing slug: {len(unresolved)}")
for t in unresolved[:30]:
    print(f"  - {t}")

# Check the TV-as-movie issue
print()
print("=== Checking Don't Trust the B ===")
import re
with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()
m2 = re.search(r'var D=(.+?);\nvar HS=', html, re.DOTALL)
d = json.loads(m2.group(1))
tl = d.get('tl', [])
for t in tl:
    name = t.get('t','').lower()
    if 'apartment' in name or 'archer' in name and t['type'] == 'movie' or 'portlandia' in name:
        print(f"  {t['t']} | type={t['type']} | yr={t.get('yr','')} | tot={t['tot']} | eby={t.get('eby',{})}")
