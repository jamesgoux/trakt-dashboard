import re, json
with open('index.html','r',encoding='utf-8') as f:
    html = f.read()
m = re.search(r'var D=(.+?);\nvar HS=', html, re.DOTALL)
d = json.loads(m.group(1))
cup = d.get('c',{}).get('cup',[])
ttw = d.get('c',{}).get('ttw',[])
print(f'Catch-up: {len(cup)} entries, max avg: {max(c["avg"] for c in cup) if cup else 0}')
print(f'TTW: {len(ttw)} entries')
# Check if Americans is in either
for item in cup + ttw:
    if 'american' in item['n'].lower():
        print(f'  Found: {item["n"]} avg={item["avg"]} ct={item["ct"]}')
