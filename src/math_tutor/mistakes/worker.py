"""Durable job worker with renewable leases and version-checked commits."""
import base64
from datetime import timedelta
import json
from threading import Event, Thread

from ..agent import TutorError
from ..analysis import ANALYSIS_PROMPT_VERSION, ProblemAnalysis
from ..quality import QUALITY_VERSION
from ..logging import logger
from ..settings import Settings
from .models import timestamp, utc_now
from .repository import new_id


class AnalysisWorker:
    def __init__(self, service, *, tutor_factory=None):
        self.service = service
        self.database = service.database
        self.settings = service.settings
        self.tutor_factory = tutor_factory or service.tutor_factory
        self._next_sweep = utc_now() + timedelta(hours=1)

    def claim(self, now):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # Old-version jobs are no longer useful, even if their lease expired.
            conn.execute("UPDATE analysis_jobs SET status='cancelled',lease_token=NULL WHERE status IN ('pending','processing') AND EXISTS(SELECT 1 FROM mistakes m WHERE m.id=mistake_id AND m.content_version<>analysis_jobs.content_version)")
            row = conn.execute("SELECT j.* FROM analysis_jobs j JOIN mistakes m ON m.id=j.mistake_id WHERE j.content_version=m.content_version AND ((j.status='pending' AND j.next_retry_at<=?) OR (j.status='processing' AND j.lease_until<=?)) ORDER BY j.next_retry_at,j.id LIMIT 1", (timestamp(now),timestamp(now))).fetchone()
            if not row:
                return None
            token = new_id()
            conn.execute("UPDATE analysis_jobs SET status='processing',lease_token=?,lease_until=?,attempt_count=attempt_count+1 WHERE id=?", (token,timestamp(now+timedelta(seconds=self.settings.job_lease_seconds)),row['id']))
            conn.execute("UPDATE mistakes SET analysis_status='processing' WHERE id=?", (row['mistake_id'],))
            return dict(conn.execute('SELECT * FROM analysis_jobs WHERE id=?', (row['id'],)).fetchone())

    def renew(self, job):
        with self.database.connect() as conn:
            return conn.execute("UPDATE analysis_jobs SET lease_until=? WHERE id=? AND lease_token=? AND status='processing'", (timestamp(utc_now()+timedelta(seconds=self.settings.job_lease_seconds)),job['id'],job['lease_token'])).rowcount == 1

    def finish(self, job, result, now):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current = conn.execute("SELECT j.id FROM analysis_jobs j JOIN mistakes m ON m.id=j.mistake_id WHERE j.id=? AND j.lease_token=? AND j.status='processing' AND j.lease_until>? AND m.content_version=j.content_version", (job['id'],job['lease_token'],timestamp(now))).fetchone()
            if not current:
                return False
            result = ProblemAnalysis.model_validate(result)
            analysis_id = new_id()
            conn.execute('INSERT INTO analyses(id,job_id,mistake_id,content_version,payload,model,prompt_version,created_at) VALUES(?,?,?,?,?,?,?,?)', (analysis_id,job['id'],job['mistake_id'],job['content_version'],result.model_dump_json(),self.settings.model,f"{ANALYSIS_PROMPT_VERSION}+{QUALITY_VERSION}:{self.settings.quality_model_review}:{self.settings.quality_max_repairs}",timestamp(now)))
            for point in [*result.core_knowledge_points,*result.detailed_knowledge_points]:
                conn.execute('INSERT INTO mistake_knowledge_points(analysis_id,local_id) VALUES(?,?)', (analysis_id,point.id))
            state = 'ready' if result.status=='solved' else 'needs_confirmation'
            conn.execute("UPDATE mistakes SET analysis_status=?,updated_at=?,problem_text=CASE WHEN trim(problem_text)='' THEN ? ELSE problem_text END WHERE id=?", (state,timestamp(now),result.problem_text,job['mistake_id']))
            conn.execute("UPDATE analysis_jobs SET status='done',lease_token=NULL,lease_until=NULL,error_code=NULL WHERE id=?", (job['id'],))
            logger.bind(event='mistake.analysis_complete',mistake_id=job['mistake_id'],job_id=job['id'],status=state).info('Mistake analysis completed')
            return True

    def fail(self, job, exc, now):
        transient = isinstance(exc,TutorError) and (exc.error_code=='network' or exc.status_code==429 or (exc.status_code is not None and exc.status_code>=500))
        retry = transient and job['attempt_count']<=3
        code = exc.error_code if isinstance(exc,TutorError) else 'internal'
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            count = conn.execute("UPDATE analysis_jobs SET status=?,error_code=?,lease_token=NULL,lease_until=NULL,next_retry_at=? WHERE id=? AND lease_token=? AND status='processing' AND EXISTS(SELECT 1 FROM mistakes m WHERE m.id=analysis_jobs.mistake_id AND m.content_version=analysis_jobs.content_version)", ('pending' if retry else 'failed',code,timestamp(now+timedelta(seconds=[2,10,30][job['attempt_count']-1] if retry else 0)),job['id'],job['lease_token'])).rowcount
            if count:
                conn.execute('UPDATE mistakes SET analysis_status=? WHERE id=?', ('pending' if retry else 'failed',job['mistake_id']))
        logger.bind(event='mistake.analysis_error',mistake_id=job['mistake_id'],job_id=job['id'],error_code=code,retry=retry).warning('Mistake analysis failed')

    def run_once(self, now=None):
        fixed_clock = now is not None
        now = now or utc_now()
        if now >= self._next_sweep:
            self.service.storage.sweep_orphans(self.database, now)
            self._next_sweep = now + timedelta(hours=1)
        cleaned = self.cleanup_once()
        job = self.claim(now)
        if job is None:
            return cleaned
        stopped = Event()
        def heartbeat():
            while not stopped.wait(self.settings.job_lease_seconds/3):
                try:
                    if not self.renew(job):
                        return
                except Exception:
                    logger.bind(event='worker.renew_error',job_id=job['id']).warning('Lease renewal failed')
        thread = Thread(target=heartbeat,daemon=True)
        thread.start()
        try:
            with self.database.connect() as conn:
                mistake = conn.execute('SELECT * FROM mistakes WHERE id=?', (job['mistake_id'],)).fetchone()
                teaching_grade = mistake['grade'] if mistake and mistake['grade'] is not None else None
                if mistake and teaching_grade is None:
                    from uuid import UUID
                    from .models import StudentContext
                    teaching_grade = self.service.learning.get_preferences(conn,StudentContext(UUID(mistake['student_id']),self.settings.student_timezone)).grade
                asset = conn.execute("SELECT * FROM assets WHERE mistake_id=? AND purpose='question'", (job['mistake_id'],)).fetchone()
            if mistake is None or asset is None:
                return True
            raw = self.service.storage.read(asset['storage_key'])
            data_url = f"data:{asset['mime']};base64,"+base64.b64encode(raw).decode()
            values = self.settings.model_dump()
            values['grade'] = teaching_grade
            with logger.contextualize(mistake_id=job['mistake_id'],job_id=job['id']):
                with self.tutor_factory(Settings.model_validate(values)) as tutor:
                    result = tutor.analyze_problem(mistake['problem_text'],image=data_url)
                self.finish(job,result,now if fixed_clock else utc_now())
        except Exception as exc:
            self.fail(job,exc,now if fixed_clock else utc_now())
        finally:
            stopped.set()
            thread.join(timeout=2)
        return True

    def cleanup_once(self):
        with self.database.connect() as conn:
            row = conn.execute('SELECT storage_key FROM cleanup_jobs ORDER BY created_at LIMIT 1').fetchone()
        if row is None:
            return False
        try:
            self.service.storage.delete(row['storage_key'])
            with self.database.connect() as conn:
                conn.execute('DELETE FROM cleanup_jobs WHERE storage_key=?', (row['storage_key'],))
            return True
        except OSError:
            logger.bind(event='asset.cleanup_error').warning('Image cleanup will be retried')
            return False
