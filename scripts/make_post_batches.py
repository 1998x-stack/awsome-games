#!/usr/bin/env python3
"""Audit frozen post-lead batches without modifying adjudications or SQLite."""
from __future__ import annotations
import argparse
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INFILE=ROOT/'data/research/v1/entities.json'
OUTFILE=ROOT/'data/research/review_batches/2026-11-17.json'
GAME='游戏/交互信号'
OTHER='其他/未分类'
GROUPS=[
 ('P00_MAPPED','P0','Existing mapped links need independent verification'),
 ('P01_CANDIDATE','P0','Existing candidate links must not be promoted without direct evidence'),
 ('P10_REPO_LEADS','P1','Verify linked source repositories and same-author relationship'),
 ('P20_GAME_PLAY','P1','Confirm original playable endpoint and whether one post maps to multiple works'),
 ('P21_OTHER_PLAY','P2','Determine whether the demo is an interactive work or another artifact'),
 ('P30_GAME_NO_LINK','P2','Request original work or source evidence; avoid title-only joins'),
 ('P40_OTHER_NO_LINK','P3','Classify category before matching to game'),
 ('P50_VIDEO_SCENE_TOOL','P3','Triage non-game and non-playable posts before work matching')
]
def group(r):
    if r['match_status']=='MAPPED':return 'P00_MAPPED'
    if r['match_status']=='CANDIDATE':return 'P01_CANDIDATE'
    if r['match_status']!='UNRESOLVED':raise ValueError('unknown match status')
    if r.get('repository_url_count',0):return 'P10_REPO_LEADS'
    if r.get('kind_signal')==GAME and r.get('play_url_count',0):return 'P20_GAME_PLAY'
    if r.get('kind_signal')==OTHER and r.get('play_url_count',0):return 'P21_OTHER_PLAY'
    if r.get('kind_signal')==GAME:return 'P30_GAME_NO_LINK'
    if r.get('kind_signal')==OTHER:return 'P40_OTHER_NO_LINK'
    return 'P50_VIDEO_SCENE_TOOL'
def build(source:Path=INFILE):
    data=json.loads(source.read_text(encoding='utf-8'))
    rows=data['records']
    groups={name:[] for name,_,_ in GROUPS}
    for x in rows:groups[group(x)].append(x)
    batches=[]
    for name,priority,action in GROUPS:
        subset=sorted(groups[name],key=lambda x:str(x['post_id']))
        for n,start in enumerate(range(0,len(subset),25),1):
            chunk=subset[start:start+25]
            batches.append({'batch_id':f'{name}_{n:02d}','priority':priority,
               'queue_state':'UNREVIEWED','decision_rule':action,
               'records':[{'post_key':r['post_id'],'post_url':r['post_url'],
                  'match_status':r['match_status'],'kind_signal':r['kind_signal'],
                  'work_id':r.get('work_id') or None,
                  'repo_urls':r.get('repository_urls') or [],
                  'play_urls':r.get('play_urls') or [],
                  'source_count':r.get('source_count') or 1} for r in chunk]})
    statuses=Counter(x['match_status'] for x in rows)
    result={'schema_version':1,'source_path':'data/research/v1/entities.json',
      'source_revision':'687e56a564bba2f95c0411b5b3bc2357f481ceae',
      'read_only':True,'source_capture':data['captured_at'],
      'warning':'907 post leads are NOT 907 games. These are UNREVIEWED work orders, not approvals or source verification.',
      'total_posts':len(rows),'mapped_posts':statuses['MAPPED'],
      'candidate_posts':statuses['CANDIDATE'],'unresolved_posts':statuses['UNRESOLVED'],
      'groups':[{'id':name,'priority':priority,'instruction':action,
        'posts':len(groups[name]),
        'batches':sum(x['batch_id'].startswith(name+'_') for x in batches)}
        for name,priority,action in GROUPS],
      'batches':batches}
    if sum(len(x['records']) for x in batches)!=len(rows):raise AssertionError('missing posts')
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check',action='store_true')
    args=p.parse_args()
    obj=build()
    expected=json.loads(OUTFILE.read_text(encoding='utf-8'))
    if args.check and expected!=obj:raise SystemExit('post review batches drift from frozen snapshot')
    if not args.check:
        OUTFILE.parent.mkdir(parents=True,exist_ok=True)
        OUTFILE.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:obj[k] for k in ('total_posts','mapped_posts','candidate_posts','unresolved_posts')},ensure_ascii=False))
if __name__=='__main__':main()
