"""Student-scoped repository. Background workers use explicit job capabilities."""
import base64
import json
from uuid import uuid4
from fastapi import HTTPException
from .models import timestamp


def new_id():
    return str(uuid4())


class Repository:
    def __init__(self, database):
        self.database = database

    def get(self, conn, student, mistake_id):
        row = conn.execute('SELECT * FROM mistakes WHERE id=? AND student_id=?', (str(mistake_id),str(student.student_id))).fetchone()
        if row is None:
            raise HTTPException(404, '错题不存在。')
        return dict(row)

    def enqueue(self, conn, mistake, now=None):
        row = conn.execute("SELECT * FROM analysis_jobs WHERE mistake_id=? AND content_version=? AND status IN ('pending','processing')", (mistake['id'], mistake['content_version'])).fetchone()
        if row:
            return dict(row)
        job_id = new_id()
        now = timestamp(now)
        conn.execute('INSERT INTO analysis_jobs(id,mistake_id,content_version,next_retry_at,created_at) VALUES(?,?,?,?,?)', (job_id,mistake['id'],mistake['content_version'],now,now))
        conn.execute("UPDATE mistakes SET analysis_status='pending' WHERE id=?", (mistake['id'],))
        return dict(conn.execute('SELECT * FROM analysis_jobs WHERE id=?', (job_id,)).fetchone())

    def detail(self, conn, student, mistake_id, include_solution=False):
        record = self.get(conn, student, mistake_id)
        assets = [dict(row) for row in conn.execute('SELECT id,purpose,mime,size FROM assets WHERE mistake_id=? AND student_id=?', (record['id'],str(student.student_id)))]
        for asset in assets:
            asset['url'] = f"/v1/mistakes/{record['id']}/assets/{asset['id']}"
        record['assets'] = assets
        analysis = conn.execute('SELECT * FROM analyses WHERE mistake_id=? AND content_version=? ORDER BY created_at DESC LIMIT 1', (record['id'],record['content_version'])).fetchone()
        record['analysis'] = None
        if analysis:
            payload = json.loads(analysis['payload'])
            if not include_solution:
                payload.pop('answer', None)
                payload.pop('steps', None)
            record['analysis'] = payload
            record['analysis_id'] = analysis['id']
            record['knowledge_mappings'] = [dict(r) for r in conn.execute('SELECT local_id,knowledge_point_id,mapping_status FROM mistake_knowledge_points WHERE analysis_id=?', (analysis['id'],))]
        record['attempts'] = [self.attempt_dict(r) for r in conn.execute('SELECT * FROM attempts WHERE mistake_id=? ORDER BY created_at,id', (record['id'],))]
        schedule = conn.execute('SELECT * FROM review_schedules WHERE mistake_id=?', (record['id'],)).fetchone()
        record['review'] = dict(schedule) if schedule else None
        return record

    @staticmethod
    def attempt_dict(row):
        result = dict(row)
        result['diagnoses'] = json.loads(result['diagnoses'])
        result['independent'] = bool(result['independent'])
        return result

    def list(self, student, filters, cursor=None, limit=20):
        conditions, args = ['m.student_id=?'], [str(student.student_id)]
        for field in ('learning_status','analysis_status'):
            if filters.get(field):
                conditions.append(f'm.{field}=?')
                args.append(filters[field])
        for field, op in (('created_from','>='),('created_to','<=')):
            if filters.get(field):
                conditions.append(f'm.created_at{op}?')
                args.append(timestamp(filters[field]))
        if filters.get('knowledge_point_id'):
            conditions.append('EXISTS(SELECT 1 FROM analyses a JOIN mistake_knowledge_points k ON k.analysis_id=a.id WHERE a.mistake_id=m.id AND a.content_version=m.content_version AND k.knowledge_point_id=?)')
            args.append(str(filters['knowledge_point_id']))
        if cursor:
            try:
                values = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if not isinstance(values, list) or len(values) != 2 or not all(isinstance(x,str) for x in values):
                    raise ValueError()
            except Exception:
                raise HTTPException(422, '分页标识无效。') from None
            conditions.append('(m.created_at,m.id)<(?,?)')
            args.extend(values)
        with self.database.connect() as conn:
            rows = [dict(r) for r in conn.execute('SELECT m.* FROM mistakes m WHERE '+' AND '.join(conditions)+' ORDER BY m.created_at DESC,m.id DESC LIMIT ?', [*args,limit+1])]
        next_cursor = None
        if len(rows)>limit:
            last = rows[limit-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps([last['created_at'],last['id']]).encode()).decode()
        return {'items': rows[:limit], 'next_cursor': next_cursor}

    def put_knowledge_point(self, point_id, name, parent_id=None, min_grade=None, max_grade=None):
        """Maintenance-only catalog operation; never expose to student routes."""
        from uuid import UUID
        point_id=str(UUID(str(point_id)))
        if not name.strip():
            raise ValueError('知识点名称不能为空。')
        with self.database.connect() as conn:
            conn.execute('INSERT INTO knowledge_points(id,name,parent_id,min_grade,max_grade) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,parent_id=excluded.parent_id,min_grade=excluded.min_grade,max_grade=excluded.max_grade',(point_id,name,str(parent_id) if parent_id else None,min_grade,max_grade))

    def map_knowledge_point(self, student, mistake_id, analysis_id, local_id, point_id):
        """Maintenance caller must authorize this operation; student scope still checked."""
        with self.database.connect() as conn:
            self.get(conn,student,mistake_id)
            analysis=conn.execute('SELECT id FROM analyses WHERE id=? AND mistake_id=?',(str(analysis_id),str(mistake_id))).fetchone()
            if not analysis:
                raise HTTPException(404,'分析不存在。')
            count=conn.execute("UPDATE mistake_knowledge_points SET knowledge_point_id=?,mapping_status='confirmed' WHERE analysis_id=? AND local_id=?",(str(point_id),str(analysis_id),local_id)).rowcount
            if not count:
                raise HTTPException(404,'局部知识点不存在。')
