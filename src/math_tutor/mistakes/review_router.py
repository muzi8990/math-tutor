"""Static stats and due-review routes, mounted before UUID detail routes."""
import base64
import json
from fastapi import APIRouter, HTTPException, Query, Request
from .router import Student,get_service
from .models import timestamp

router=APIRouter(tags=['错题复习'])


@router.get('/v1/mistakes/stats')
def stats(request: Request,student: Student):
    service=get_service(request)
    student_id=str(student.student_id)
    with service.database.connect() as conn:
        counts={state:0 for state in ('new','practicing','reviewing','mastered')}
        for row in conn.execute('SELECT learning_status,count(*) AS count FROM mistakes WHERE student_id=? GROUP BY learning_status',(student_id,)):
            counts[row['learning_status']]=row['count']
        due=conn.execute('SELECT count(*) FROM review_schedules r JOIN mistakes m ON m.id=r.mistake_id WHERE m.student_id=? AND r.next_review_at<=?',(student_id,timestamp(service.clock()))).fetchone()[0]
        aggregate=conn.execute("SELECT count(*) AS total,sum(CASE WHEN a.status='correct' THEN 1 ELSE 0 END) AS correct FROM attempts a JOIN mistakes m ON m.id=a.mistake_id WHERE m.student_id=? AND a.independent=1 AND a.status IN ('correct','incorrect')",(student_id,)).fetchone()
    total=aggregate['total']
    return {'learning_counts':counts,'mistake_count':sum(counts.values()),'due_review_count':due,'determined_independent_attempts':total,'independent_accuracy':aggregate['correct']/total if total else None}


@router.get('/v1/reviews/today')
def reviews(request: Request,student: Student,cursor: str|None=Query(None,max_length=1000),limit: int=Query(20,ge=1,le=100)):
    service=get_service(request)
    conditions=['m.student_id=?','r.next_review_at<=?']
    args=[str(student.student_id),timestamp(service.clock())]
    if cursor:
        try:
            values=json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if not isinstance(values,list) or len(values)!=2 or not all(isinstance(x,str) for x in values):
                raise ValueError()
        except Exception:
            raise HTTPException(422,'分页标识无效。') from None
        conditions.append('(r.next_review_at,m.id)>(?,?)')
        args.extend(values)
    with service.database.connect() as conn:
        rows=[dict(r) for r in conn.execute('SELECT m.*,r.next_review_at FROM mistakes m JOIN review_schedules r ON r.mistake_id=m.id WHERE '+' AND '.join(conditions)+' ORDER BY r.next_review_at,m.id LIMIT ?',[*args,limit+1])]
    next_cursor=None
    if len(rows)>limit:
        row=rows[limit-1]
        next_cursor=base64.urlsafe_b64encode(json.dumps([row['next_review_at'],row['id']]).encode()).decode()
    return {'items':rows[:limit],'next_cursor':next_cursor,'timezone':student.timezone}
