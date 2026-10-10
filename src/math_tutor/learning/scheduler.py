"""Local calendar calculation; task generation runs in a separate process."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _valid_local(day, hour, minute, zone):
    candidate=datetime(day.year,day.month,day.day,hour,minute)
    # Some zones skip an entire calendar date; bound the forward search.
    for _ in range(48*60+1):
        valid=[]
        for fold in (0,1):
            value=candidate.replace(tzinfo=zone,fold=fold).astimezone(timezone.utc)
            if value.astimezone(zone).replace(tzinfo=None)==candidate:
                valid.append(value)
        if valid:
            return min(valid)
        candidate+=timedelta(minutes=1)
    raise ValueError('无法计算有效的当地生成时间。')


def next_generation(now, preferences, *, allow_today):
    if now.tzinfo is None:
        raise ValueError('调度时钟必须包含时区。')
    if not preferences.daily_enabled:
        return None
    zone=ZoneInfo(preferences.timezone)
    day=now.astimezone(zone).date()
    if not allow_today:
        day+=timedelta(days=1)
    hour,minute=map(int,preferences.generation_time.split(':'))
    value=_valid_local(day,hour,minute,zone)
    return max(value,now.astimezone(timezone.utc)) if allow_today else value


class LearningScheduler:
    def __init__(self, database, clock=None):
        from ..mistakes.models import utc_now
        self.database=database
        self.clock=clock or utc_now

    def run_once(self):
        from uuid import UUID
        from ..logging import logger
        from ..mistakes.models import StudentContext, timestamp
        from .repository import LearningRepository
        from .service import LearningService
        now=self.clock()
        result={'generated':0,'existing':0,'failed':0}
        with self.database.connect() as conn:
            students=[r['student_id'] for r in conn.execute('''SELECT student_id FROM learning_preferences
                WHERE daily_enabled=1 AND next_run_at<=? ORDER BY next_run_at,student_id''',(timestamp(now),))]
        service=LearningService(self.database,clock=self.clock)
        repository=LearningRepository(self.database)
        for student_id in students:
            try:
                with self.database.connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    row=conn.execute('SELECT * FROM learning_preferences WHERE student_id=?',(student_id,)).fetchone()
                    if not row or not row['daily_enabled'] or not row['next_run_at'] or datetime.fromisoformat(row['next_run_at'])>now:
                        continue
                    preferences=repository.get_preferences(conn,StudentContext(UUID(student_id)))
                    due=next_generation(now,preferences,allow_today=True)
                    if due>now:
                        # Restart before today's time: schedule today, never generate old dates.
                        conn.execute('UPDATE learning_preferences SET next_run_at=? WHERE student_id=?',(timestamp(due),student_id))
                        continue
                    day=now.astimezone(ZoneInfo(preferences.timezone)).date().isoformat()
                    existed=conn.execute('SELECT 1 FROM daily_tasks WHERE student_id=? AND local_date=?',(student_id,day)).fetchone()
                    service.generate_for_student(conn,student_id,preferences,now,'scheduled')
                    conn.execute('UPDATE learning_preferences SET next_run_at=? WHERE student_id=?',
                        (timestamp(next_generation(now,preferences,allow_today=False)),student_id))
                result['existing' if existed else 'generated']+=1
            except Exception:
                result['failed']+=1
                logger.bind(event='learning.schedule_failed',student_id=student_id).warning('Daily task generation failed; retry on next scan')
        logger.bind(event='learning.scheduler_scan',**result).info('Learning scheduler scan completed')
        return result
