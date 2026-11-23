# Author: Codex (IIC)
import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
script = Path(__file__).with_name("export_teleop_trial.py")
with tempfile.TemporaryDirectory() as folder:
    p=Path(folder)
    def save(name,obj):
        (p/name).write_text(json.dumps(obj))
    def lines(name, rows):
        (p/name).write_text(''.join(json.dumps(r)+'\n' for r in rows))
    def call():
        return subprocess.run([sys.executable, '-B',script,str(p)],text=True,capture_output=True)
    def read(n):
        return list(csv.DictReader((p/n).open()))
    meta = {
        'joint_indices': [f'joint_{i}' for i in range(29)],
        'joints': ['q_rad', 'dq_rad_s', 'tau_est_Nm'],
        'targets': ['mode', 'q_rad', 'dq_rad_s', 'tau_Nm', 'kp', 'kd'],
    }
    save('capture.json',meta)
    now=datetime.now(timezone.utc)
    def utc(t):return (now+timedelta(seconds=t)).isoformat()
    cmds=[(1,0,(.15,0,0),1),(2,.1,(.15,0,0),.9),(3,.4,(0,0,0),1),(4,.45,(-.15,0,.3),.01),
          (5,.5,(-.15,0,-.3),.3),(6,.55,(.15,.10,0),.2),(7,.76,(-.15,0,0),.2),(8,.97,(.9,.1,0),0)]
    reqs=[dict(id=i,utc=utc(t),mono_ns=round(t*1e9),api=7105,topic='rt/api/sport/request',body=dict(velocity=v,duration=d)) for i,t,v,d in cmds]
    reply=[dict(id=1,api=7105,code=0,topic='rt/api/sport/response'),dict(id=2,api=7105,code=12,topic='rt/api/sport/response'),dict(id=1,api=7105,code=33,topic='rt/api/loco/response')]
    lines('rpc.jsonl',reqs+reply)
    def sample(topic,t,v,mode=0):
        item=dict(topic=topic,utc=utc(t),mono_ns=round(t*1e9),mode_pr=mode,mode_machine=3)
        if topic=='rt/lowstate':item.update(joints=[[v,0.5,None] for i in range(29)],tick=333)
        else:item.update(targets=[[1,v,None,None,2,3] for i in range(29)])
        return item
    lines('motors.jsonl',[sample('rt/lowstate',.2,2),sample('rt/lowstate',.1,1),sample('rt/lowcmd',.4,8),
          sample('rt/lowcmd',.53,3),sample('rt/lowstate',.7,7),sample('rt/lowcmd',.7,3,1)])
    assert call().returncode != 0 and not list(p.glob('joint*.csv'))
    save('capture-end.json',dict(end_utc=utc(2),queue_drops={'rt/lowstate':1}))
    done=call()
    assert done.returncode == 0, done.stderr
    print(done.stdout.strip())
    w=json.loads((p/'movement-windows.json').read_text())['windows']
    assert [r['key_equivalent'] for r in w]==['i|I','.','m','U',',|<','']
    assert [(r['nominal_seconds'],r['feedback_samples'],r['target_samples']) for r in w] == [(.4,2,0),(.01,0,0),(.05,0,1),(.2,1,1),(.2,0,0),(0,0,0)]
    assert w[0]['response_counts']=={'0':1,'12':1} and w[1]['response_counts']=={'unmatched':1}
    sf,st,ss=map(read,['joint-feedback.csv','joint-targets.csv','joint-window-summary.csv'])
    assert len(sf)==87 and len(st)==87 and len(ss)==29*6+6
    assert ss[0]['measured_net_change_deg']==ss[0]['measured_span_deg'] != '' and ss[0]['target_min_deg']==''
    assert all(r['measured_min_deg']==r['target_min_deg']=='' for r in ss if r['window']=='2')
    assert all(r['window']=='' for r in st[:29])
    files=list(p.glob('joint*.csv'))+[p/'movement-windows.json']
    saved=[f.stat().st_mtime_ns for f in files]
    assert call().returncode != 0 and [f.stat().st_mtime_ns for f in files]==saved
    for f in files:f.unlink()
    lines('motors.jsonl',[]);lines('rpc.jsonl',[])
    done=call()
    assert done.returncode==0 and read('joint-window-summary.csv')==[] and read('joint-feedback.csv')==[]
    for f in files:f.unlink()
    lines('motors.jsonl',[dict(topic='rt/lowcmd',mono_ns=50,mode_pr=0,targets=[])])
    assert call().returncode!=0 and not any(f.exists() for f in files)
print("Fixture passed: no live writes, 29 slots, merged/replaced/zero/expired durations, missing samples and responses, key aliases, PR/AB basis, precise clipping, nonzero errors, exclusive rerun, rollback, entirely empty trial.")
