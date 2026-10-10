"""SQL operations consume their caller's connection and transaction."""
from ..mistakes.models import timestamp
from .schemas import LearningPreferences


class LearningRepository:
    def __init__(self, database):
        self.database = database

    def get_preferences(self, conn, student):
        row = conn.execute('SELECT * FROM learning_preferences WHERE student_id=?', (str(student.student_id),)).fetchone()
        if row is None:
            return LearningPreferences(timezone=student.timezone)
        return LearningPreferences(**{key: (bool(row[key]) if key == 'daily_enabled' else row[key]) for key in LearningPreferences.model_fields})

    def save_preferences(self, conn, student, preferences, next_run_at):
        conn.execute('''INSERT INTO learning_preferences(student_id,grade,timezone,daily_enabled,generation_time,daily_limit,next_run_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(student_id) DO UPDATE SET grade=excluded.grade,timezone=excluded.timezone,
            daily_enabled=excluded.daily_enabled,generation_time=excluded.generation_time,daily_limit=excluded.daily_limit,
            next_run_at=excluded.next_run_at,updated_at=excluded.updated_at''',
            (str(student.student_id),preferences.grade,preferences.timezone,int(preferences.daily_enabled),preferences.generation_time,
             preferences.daily_limit,timestamp(next_run_at) if next_run_at else None,timestamp()))
        return preferences

    def candidates(self, conn, student_id, now):
        import json
        from datetime import datetime
        from .models import ReviewCandidate
        rows=conn.execute('''SELECT m.*,r.next_review_at,a.id AS analysis_id,a.payload
            FROM mistakes m LEFT JOIN review_schedules r ON r.mistake_id=m.id
            JOIN analyses a ON a.mistake_id=m.id AND a.content_version=m.content_version
            WHERE m.student_id=? AND m.analysis_status='ready' AND NOT EXISTS(
                SELECT 1 FROM analyses newer WHERE newer.mistake_id=m.id AND newer.content_version=m.content_version
                AND (newer.created_at,newer.id)>(a.created_at,a.id))''',(str(student_id),)).fetchall()
        result=[]
        for row in rows:
            payload=json.loads(row['payload'])
            if payload.get('status')!='solved':
                continue
            due=datetime.fromisoformat(row['next_review_at']) if row['next_review_at'] else None
            if due and due>now:
                continue
            if due is None and row['learning_status']=='mastered':
                continue
            details={p['id'] for p in payload.get('detailed_knowledge_points',[])}
            mappings=[r['knowledge_point_id'] for r in conn.execute('''SELECT k.local_id,k.knowledge_point_id
                FROM mistake_knowledge_points k JOIN knowledge_points p ON p.id=k.knowledge_point_id
                WHERE k.analysis_id=? AND k.mapping_status='confirmed' AND p.parent_id IS NOT NULL''',(row['analysis_id'],))
                if r['local_id'] in details]
            result.append(ReviewCandidate(row['id'],row['content_version'],datetime.fromisoformat(row['created_at']),due,
                min(mappings) if mappings else 'unmapped:'+row['id'],'due_review' if due else 'new_mistake'))
        return result

    def task(self, conn, student_id, task_id):
        from fastapi import HTTPException
        from .models import DailyTask, TaskItem
        row=conn.execute('SELECT * FROM daily_tasks WHERE id=? AND student_id=?',(str(task_id),str(student_id))).fetchone()
        if row is None:
            raise HTTPException(404,'复习任务不存在。')
        self.reconcile_task(conn,row['id'])
        items=[TaskItem.model_validate(dict(r)) for r in conn.execute('SELECT * FROM daily_task_items WHERE task_id=? ORDER BY position',(row['id'],))]
        available=[i for i in items if i.status!='invalidated']
        return DailyTask(**{k:row[k] for k in ('id','local_date','timezone','source','policy_version','created_at')},items=items,
            completed_count=sum(i.status=='completed' for i in available),available_count=len(available),
            message='今日暂无待复习错题。' if not items else None)

    def reconcile_task(self, conn, task_id):
        """Invalidation is permanent; re-analysis never silently revives an item."""
        import json
        rows=conn.execute('''SELECT i.id,i.mistake_id,i.content_version,m.content_version AS current_version,m.analysis_status
            FROM daily_task_items i LEFT JOIN mistakes m ON m.id=i.mistake_id WHERE i.task_id=? AND i.status!='invalidated' ''',(task_id,)).fetchall()
        for row in rows:
            invalid=row['mistake_id'] is None or row['current_version']!=row['content_version'] or row['analysis_status']!='ready'
            if not invalid:
                analysis=conn.execute('SELECT payload FROM analyses WHERE mistake_id=? AND content_version=? ORDER BY created_at DESC,id DESC LIMIT 1',
                    (row['mistake_id'],row['content_version'])).fetchone()
                invalid=analysis is None or json.loads(analysis['payload']).get('status')!='solved'
            if invalid:
                conn.execute("UPDATE daily_task_items SET status='invalidated' WHERE id=?",(row['id'],))

    def invalidate_mistake(self, conn, student, mistake_id):
        conn.execute('''UPDATE daily_task_items SET status='invalidated' WHERE mistake_id=? AND task_id IN
            (SELECT id FROM daily_tasks WHERE student_id=?)''',(str(mistake_id),str(student.student_id)))

    def _item(self, conn, student, item_id):
        from fastapi import HTTPException
        row=conn.execute('''SELECT i.* FROM daily_task_items i JOIN daily_tasks t ON t.id=i.task_id
            WHERE i.id=? AND t.student_id=?''',(str(item_id),str(student.student_id))).fetchone()
        if row is None:
            raise HTTPException(404,'复习任务项不存在。')
        self.reconcile_task(conn,row['task_id'])
        return conn.execute('SELECT * FROM daily_task_items WHERE id=?',(str(item_id),)).fetchone()

    def bind_practice(self, conn, student, mistake, item_id, practice_id):
        from fastapi import HTTPException
        row=self._item(conn,student,item_id)
        if row['mistake_id']!=mistake['id'] or row['content_version']!=mistake['content_version'] or row['status'] in ('completed','invalidated'):
            raise HTTPException(409,'任务项已完成、已失效或与题目不匹配。')
        conn.execute('UPDATE practice_sessions SET daily_task_item_id=? WHERE id=?',(str(item_id),str(practice_id)))

    def validate_practice(self, conn, student, practice):
        from fastapi import HTTPException
        if practice and practice['daily_task_item_id']:
            row=self._item(conn,student,practice['daily_task_item_id'])
            if row['status']=='invalidated':
                raise HTTPException(409,'复习任务项已失效。')

    def apply_attempt(self, conn, student, practice_id, attempt):
        if not practice_id:
            return
        practice=conn.execute('SELECT * FROM practice_sessions WHERE id=?',(str(practice_id),)).fetchone()
        if not practice or not practice['daily_task_item_id']:
            return
        item=self._item(conn,student,practice['daily_task_item_id'])
        if item['status']=='invalidated':
            return
        # Multiple sessions may already have been opened before completion.
        # Recompute from persisted records; older corrections cannot steal the latest result.
        latest=conn.execute('''SELECT a.* FROM attempts a JOIN attempt_submissions s ON s.attempt_id=a.id AND s.status='done'
            JOIN practice_sessions p ON p.id=s.practice_id WHERE p.daily_task_item_id=? AND a.content_version=?
            ORDER BY a.created_at DESC,a.id DESC LIMIT 1''',(item['id'],item['content_version'])).fetchone()
        if latest:
            status='needs_confirmation' if latest['status']=='undetermined' else 'completed'
            conn.execute('UPDATE daily_task_items SET status=?,attempt_id=?,outcome=?,independent=? WHERE id=?',
                (status,latest['id'],latest['status'],latest['independent'],item['id']))
