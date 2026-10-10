"""Deterministic performance states, not standardized ability scores."""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
import json
from zoneinfo import ZoneInfo
from .models import AbilityEvidence, AbilitySummary
from .repository import LearningRepository

ABILITY_VERSION = 'ability-v1'


def collect_evidence(conn, student, now):
    if now.tzinfo is None:
        raise ValueError('评估时钟必须包含时区。')
    preferences=LearningRepository(None).get_preferences(conn,student)
    zone=ZoneInfo(preferences.timezone)
    today=now.astimezone(zone).date()
    start=datetime.combine(today-timedelta(days=29),time.min,zone).astimezone(timezone.utc)
    rows=conn.execute('''SELECT a.*,an.payload FROM attempts a
        JOIN mistakes m ON m.id=a.mistake_id
        JOIN analyses an ON an.id=a.analysis_id AND an.mistake_id=m.id AND an.content_version=a.content_version
        WHERE m.student_id=? AND a.content_version=m.content_version AND a.independent=1 AND a.hint_count=0
        AND a.status IN ('correct','incorrect') AND a.created_at>=? AND a.created_at<=?
        ORDER BY a.created_at,a.id''',(str(student.student_id),start.isoformat(),now.astimezone(timezone.utc).isoformat())).fetchall()
    latest={}
    for row in rows:
        created=datetime.fromisoformat(row['created_at'])
        latest[(row['mistake_id'],created.astimezone(zone).date())]=row
    evidence=[]
    mapping_cache={}
    for (mid,day),row in latest.items():
        payload=json.loads(row['payload'])
        if payload.get('status')!='solved':
            continue
        details={p['id'] for p in payload.get('detailed_knowledge_points',[])}
        aid=row['analysis_id']
        if aid not in mapping_cache:
            mapping_cache[aid]={r['local_id']:r['knowledge_point_id'] for r in conn.execute('''
                SELECT k.local_id,k.knowledge_point_id FROM mistake_knowledge_points k
                JOIN knowledge_points p ON p.id=k.knowledge_point_id
                WHERE k.analysis_id=? AND k.mapping_status='confirmed' AND p.parent_id IS NOT NULL''',(aid,))}
        mappings=mapping_cache[aid]
        local_ids=details
        if row['status']=='incorrect':
            local_ids={ident for d in json.loads(row['diagnoses']) if d.get('category')!='unknown' and d.get('evidence','').strip()
                for ident in d.get('knowledge_point_ids',[]) if ident in details}
        for point_id in sorted({mappings[k] for k in local_ids if k in mappings}):
            evidence.append(AbilityEvidence(point_id,mid,row['id'],aid,datetime.fromisoformat(row['created_at']),day,
                row['status']=='correct',row['provenance']))
    return evidence


def summarize(evidence):
    groups=defaultdict(list)
    for item in evidence:
        groups[item.point_id].append(item)
    result=[]
    for point_id,items in sorted(groups.items()):
        items.sort(key=lambda e:(e.created_at,e.attempt_id))
        count=len(items); questions=len({e.mistake_id for e in items}); dates=len({e.local_date for e in items})
        correct=sum(e.correct for e in items); accuracy=correct/count
        last=items[-2:]
        if count<3 or questions<2:
            state='insufficient_evidence'
        elif accuracy<0.6 or all(not e.correct for e in last):
            state='needs_practice'
        elif count>=5 and questions>=3 and dates>=2 and accuracy>=0.8 and all(e.correct for e in last):
            state='stable'
        else:
            state='basic'
        result.append(AbilitySummary(point_id=point_id,evidence_count=count,question_count=questions,date_count=dates,
            accuracy=accuracy,state=state,recent_errors=[e.attempt_id for e in items[-5:] if not e.correct],evidence=items))
    return result


def assessment(conn, student, now):
    """Include mapped points with no evidence and aggregate parent state counts."""
    summaries={item.point_id:item for item in summarize(collect_evidence(conn,student,now))}
    points=conn.execute('''SELECT DISTINCT p.* FROM knowledge_points p
        JOIN mistake_knowledge_points k ON k.knowledge_point_id=p.id AND k.mapping_status='confirmed'
        JOIN analyses a ON a.id=k.analysis_id JOIN mistakes m ON m.id=a.mistake_id
        WHERE m.student_id=? AND m.content_version=a.content_version AND p.parent_id IS NOT NULL
        ORDER BY p.id''',(str(student.student_id),)).fetchall()
    details=[]; cores={}
    for point in points:
        item=summaries.get(point['id']) or AbilitySummary(point_id=point['id'],evidence_count=0,question_count=0,date_count=0,
            accuracy=None,state='insufficient_evidence')
        details.append({**item.model_dump(mode='json'),'name':point['name'],'parent_id':point['parent_id'],
            'min_grade':point['min_grade'],'max_grade':point['max_grade']})
        core=cores.setdefault(point['parent_id'],defaultdict(int)); core[item.state]+=1
    parent_names={r['id']:r['name'] for r in conn.execute('SELECT id,name FROM knowledge_points WHERE parent_id IS NULL')}
    return {'policy_version':ABILITY_VERSION,'window_days':30,'as_of':now.isoformat(),'items':details,
        'core_summary':[{'point_id':pid,'name':parent_names.get(pid),'state_counts':dict(counts)} for pid,counts in sorted(cores.items())]}
