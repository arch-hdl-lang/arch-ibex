import re,sys
path,want=sys.argv[1],sys.argv[2].split(',')
txt=open(path).read()
scope=[];ids={}
for line in txt.split('$enddefinitions')[0].split('\n'):
    t=line.split()
    if not t: continue
    if t[0]=='$scope': scope.append(t[2])
    elif t[0]=='$upscope': scope.pop()
    elif t[0]=='$var':
        name='.'.join(scope+[t[4]])
        for w in want:
            if name.endswith('.'+w) or name==w:
                ids.setdefault(t[3],[]).append(w)
body=txt.split('$enddefinitions $end')[1]
vals={};rows=[];t=None
for line in body.split('\n'):
    line=line.strip()
    if not line: continue
    if line.startswith('#'):
        if t is not None: rows.append((t,dict(vals)))
        t=int(line[1:]);continue
    m=re.match(r'^b([01xz]+)\s+(\S+)$',line) or re.match(r'^([01xz])(\S+)$',line)
    if m and m.group(2) in ids:
        for w in ids[m.group(2)]: vals[w]=m.group(1)
if t is not None: rows.append((t,dict(vals)))
def v(x): return str(int(x,2)) if x and set(x)<=set('01') else (x or '?')
step=sorted(set(r[0] for r in rows))
period=step[1]-step[0] if len(step)>1 else 1
print('step '+' '.join(f'{w[:10]:>10}' for w in want))
for tt,vv in rows:
    print(f'{tt//period:4d} '+' '.join(f'{v(vv.get(w)):>10}' for w in want))
