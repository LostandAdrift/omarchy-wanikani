#!/usr/bin/env python3
"""Reproducible local benchmark with 9,000 authored fixture subjects, no API."""
import copy
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wanikani.store import Store
from wanikani.engine import Engine
from wanikani.demo import populate
from wanikani.common import stamp

def timing(fn, count):
    samples=[]
    for i in range(count):
        before=time.perf_counter_ns();fn(i);samples.append((time.perf_counter_ns()-before)/1e6)
    return {'median_ms':round(statistics.median(samples),3),'p95_ms':round(sorted(samples)[int(len(samples)*.95)-1],3),'samples':count}

def main():
    with tempfile.TemporaryDirectory() as temporary:
        s=Store(Path(temporary)/'benchmark.sqlite3');now=time.time();populate(s,now)
        subject=s.subject(1);assignment=s.related('assignment',1)
        with s.transaction():
            user=s.get('user');user['data']['subscription']['max_level_granted']=60;s.set('user',user)
            for sid in range(100,9100):
                item=copy.deepcopy(subject);item['id']=sid;item['data']['level']=sid%60+1
                item['data']['meaning_mnemonic']='Independently authored sample mnemonic. '*20
                s.put(item)
                a=copy.deepcopy(assignment);a['id']=sid+10000;a['data']['subject_id']=sid
                a['data']['available_at']=stamp(now-60 if sid%3==0 else now+sid*60);s.put(a)
        e=Engine(s)
        print(json.dumps({'subjects':9016,'snapshot':timing(lambda _:e.snapshot(),8),'search':timing(lambda _:e.search('ground'),8)},indent=2),flush=True)
        e.start('practice',1,[1])
        def answer(i):
            e.command('answer-'+str(i),'answer',{'text':'wrong'})
            e.command('advance-'+str(i),'advance',{})
        print(json.dumps({'answer_and_advance':timing(answer,100)},indent=2),flush=True)
        s.close()
if __name__=='__main__':main()
