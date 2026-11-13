import re,sys,struct,os,collections
def dds(p):
    try:
        raw=open(p,'rb').read(148); h,w=struct.unpack_from('<2I',raw,12); return w,h,struct.unpack_from('<I',raw,128)[0]
    except Exception: return None
for cap in sys.argv[1:]:
    d=f'runtime/replay/{cap}' if os.path.isdir(f'runtime/replay/{cap}') else f'runtime/replay/n1-fake-{cap}'  # a run label, or a capture id
    mats={}; meshes={}
    for line in open(d+'/fake-remix.log',errors='replace'):
        if 'CreateMaterial path=' in line:
            kv=dict(re.findall(r'(\w+)=(\S+)',line)); mats[kv['id']]=kv
        elif 'CreateMesh hash=' in line:
            kv=dict(re.findall(r'(\w+)=(\S+)',line)); meshes[kv['key']]=kv
    tot=sum(int(m['indices']) for m in meshes.values())
    cls=collections.Counter(); n=collections.Counter()
    uniform=collections.Counter()
    for m in meshes.values():
        mat=mats.get(m['mat'])
        if not mat: c='no material line'
        else:
            r,me=mat['roughness']!='-',mat['metallic']!='-'
            c={(1,1):'rough+metal textures',(0,1):'metal texture only',(1,0):'rough texture only',(0,0):'constants only (0.6 / 0)'}[(r,me)]
            if r or me:
                f=mat['metallic'] if me else mat['roughness']
                s=dds(d+'/live-textures/'+f)
                if s and s[0]<=32: c+=' (<=32px mask: placeholder)'
            a=dds(d+'/live-textures/'+mat['path'])
            if a and a[0]<=32: uniform['albedo <=32px']+=int(m['indices'])
            if mat['alpha'].split('/')[0]!='7': uniform['alpha-tested']+=int(m['indices'])
            # L3: a constant the game's own flag chose (the fake runtime logs them; defaults are albedo 1, metal 0, rough 0.6)
            if mat.get('mconst', '0.000')!='0.000' or mat.get('rconst', '0.600')!='0.600' or mat.get('aconst', '1.000,1.000,1.000')!='1.000,1.000,1.000':
                uniform['constants from flags']+=int(m['indices'])
        cls[c]+=int(m['indices']); n[c]+=1
    print(f'== {cap}: {len(meshes)} meshes, {len(mats)} materials, {tot//3} triangles')
    for c,v in cls.most_common(): print(f'  {c:50s} meshes={n[c]:5d} tris={v//3:8d} {100*v/tot:5.1f}%')
    for c,v in uniform.items(): print(f'  [{c}] {100*v/tot:.1f}% of triangles')
