"""Learning use cases with short transactions and no model calls."""
from datetime import datetime
from zoneinfo import ZoneInfo
from ..mistakes.models import StudentContext, timestamp, utc_now
from ..mistakes.repository import new_id
from .repository import LearningRepository
from .planning import PLANNING_VERSION, select_candidates
from .ability import assessment
from .scheduler import next_generation


class LearningService:
    def __init__(self, database, clock=utc_now):
        self.database=database
        self.repository=LearningRepository(database)
        self.clock=clock

    def preferences(self, student):
        with self.database.connect() as conn:
            return self.repository.get_preferences(conn,student)

    def update_preferences(self, student, preferences):
        if 'timezone' not in preferences.model_fields_set:
            # A missing field uses this student's authenticated default,
            # never a fixed locale that silently changes calendar boundaries.
            from .schemas import LearningPreferences
            preferences=LearningPreferences.model_validate({**preferences.model_dump(),'timezone':student.timezone})
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            return self.repository.save_preferences(conn,student,preferences,next_generation(self.clock(),preferences,allow_today=True))

    def abilities(self, student):
        with self.database.connect() as conn:
            return assessment(conn,student,self.clock())

    def generate_for_student(self, conn, student_id, preferences, now, source):
        if now.tzinfo is None:
            raise ValueError('任务时钟必须包含时区。')
        day=now.astimezone(ZoneInfo(preferences.timezone)).date().isoformat()
        existing=conn.execute('SELECT id FROM daily_tasks WHERE student_id=? AND local_date=?',(str(student_id),day)).fetchone()
        if existing:
            return self.repository.task(conn,student_id,existing['id'])
        task_id=new_id()
        conn.execute('INSERT INTO daily_tasks VALUES(?,?,?,?,?,?,?)',(task_id,str(student_id),day,preferences.timezone,source,PLANNING_VERSION,timestamp(now)))
        candidates=select_candidates(self.repository.candidates(conn,student_id,now),preferences.daily_limit)
        for position,item in enumerate(candidates):
            conn.execute('''INSERT INTO daily_task_items(id,task_id,mistake_id,mistake_id_snapshot,content_version,reason,due_at,position)
                VALUES(?,?,?,?,?,?,?,?)''',(new_id(),task_id,item.mistake_id,item.mistake_id,item.content_version,item.reason,
                timestamp(item.due_at) if item.due_at else None,position))
        return self.repository.task(conn,student_id,task_id)

    def generate_today(self, student, source='manual'):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            preferences=self.repository.get_preferences(conn,student)
            exists=conn.execute('SELECT 1 FROM learning_preferences WHERE student_id=?',(str(student.student_id),)).fetchone()
            if not exists:
                self.repository.save_preferences(conn,student,preferences,next_generation(self.clock(),preferences,allow_today=True))
            return self.generate_for_student(conn,str(student.student_id),preferences,self.clock(),source)

    def today(self, student):
        from fastapi import HTTPException
        with self.database.connect() as conn:
            preferences=self.repository.get_preferences(conn,student)
            day=self.clock().astimezone(ZoneInfo(preferences.timezone)).date().isoformat()
            row=conn.execute('SELECT id FROM daily_tasks WHERE student_id=? AND local_date=?',(str(student.student_id),day)).fetchone()
            if row is None:
                raise HTTPException(404,'今天尚未生成复习任务。')
            return self.repository.task(conn,student.student_id,row['id'])

    def get_task(self, student, task_id):
        with self.database.connect() as conn:
            return self.repository.task(conn,student.student_id,task_id)
