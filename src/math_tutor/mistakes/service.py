import hashlib
from fastapi import HTTPException
from .models import timestamp
from .repository import Repository, new_id


class MistakeService:
    def __init__(self, database, storage, settings, tutor_factory):
        self.database, self.storage, self.settings = database, storage, settings
        self.repository = Repository(database)
        self.tutor_factory = tutor_factory
        from ..learning.repository import LearningRepository
        self.learning = LearningRepository(database)
        from .models import utc_now
        self.clock = utc_now

    def create(self, student, image, mime, text='', grade=None, note='', allow_duplicate=False):
        asset = self.storage.put(student.student_id,image,mime)
        try:
            with self.database.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                existing = conn.execute("SELECT mistake_id FROM assets WHERE student_id=? AND sha256=? AND purpose='question' LIMIT 1", (str(student.student_id),asset.sha256)).fetchone()
                if existing and not allow_duplicate:
                    raise HTTPException(409, {'code':'duplicate_image','mistake_id':existing['mistake_id'],'message':'已收录相同图片，可明确选择继续收录。'})
                mistake_id, now = new_id(), timestamp()
                conn.execute('INSERT INTO mistakes(id,student_id,problem_text,grade,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?)', (mistake_id,str(student.student_id),text,grade,note,now,now))
                conn.execute("INSERT INTO assets(id,student_id,mistake_id,purpose,storage_key,mime,size,sha256) VALUES(?,?,?,'question',?,?,?,?)", (new_id(),str(student.student_id),mistake_id,asset.storage_key,asset.mime,asset.size,asset.sha256))
                self.repository.enqueue(conn,self.repository.get(conn,student,mistake_id))
                return self.repository.detail(conn,student,mistake_id)
        except Exception:
            self.storage.delete(asset.storage_key)
            raise

    def get(self, student, mistake_id, include_solution=False):
        with self.database.connect() as conn:
            return self.repository.detail(conn,student,mistake_id,include_solution)

    def list(self, student, filters, cursor=None, limit=20):
        return self.repository.list(student,filters,cursor,limit)

    def read_asset(self, student, mistake_id, asset_id):
        with self.database.connect() as conn:
            self.repository.get(conn,student,mistake_id)
            row = conn.execute('SELECT * FROM assets WHERE id=? AND mistake_id=? AND student_id=?', (str(asset_id),str(mistake_id),str(student.student_id))).fetchone()
            if not row:
                raise HTTPException(404,'图片不存在。')
        try:
            return self.storage.read(row['storage_key']),row['mime']
        except FileNotFoundError:
            raise HTTPException(404,'图片不存在。') from None

    def enqueue_analysis(self, student, mistake_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self.learning.invalidate_mistake(conn,student,mistake_id)
            return self.repository.enqueue(conn,self.repository.get(conn,student,mistake_id))

    def update(self, student, mistake_id, patch):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = self.repository.get(conn,student,mistake_id)
            changes = patch.model_dump(exclude_unset=True)
            if any(changes.get(key) is None for key in ('text','note') if key in changes):
                raise HTTPException(422,'题干与备注不能为 null。')
            for field in ('text','grade','note'):
                if field in changes:
                    column = 'problem_text' if field=='text' else field
                    conn.execute(f'UPDATE mistakes SET {column}=?,updated_at=? WHERE id=? AND student_id=?', (changes[field],timestamp(),old['id'],str(student.student_id)))
            if 'text' in changes and changes['text']!=old['problem_text']:
                conn.execute("UPDATE mistakes SET content_version=content_version+1,analysis_status='pending',learning_status='new' WHERE id=?", (old['id'],))
                conn.execute("UPDATE analysis_jobs SET status='cancelled',lease_token=NULL WHERE mistake_id=? AND status IN ('pending','processing')", (old['id'],))
                self.learning.invalidate_mistake(conn,student,mistake_id)
                conn.execute('DELETE FROM review_schedules WHERE mistake_id=?', (old['id'],))
                self.repository.enqueue(conn,self.repository.get(conn,student,mistake_id))
            return self.repository.detail(conn,student,mistake_id)

    def delete(self, student, mistake_id):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            record=self.repository.get(conn,student,mistake_id)
            conn.execute('INSERT OR IGNORE INTO cleanup_jobs(storage_key,created_at) SELECT storage_key,? FROM assets WHERE mistake_id=? AND student_id=?', (timestamp(),record['id'],str(student.student_id)))
            self.learning.invalidate_mistake(conn,student,mistake_id)
            conn.execute('DELETE FROM mistakes WHERE id=? AND student_id=?', (record['id'],str(student.student_id)))

    def create_practice(self, student, mistake_id, daily_task_item_id=None):
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            mistake=self.repository.get(conn,student,mistake_id)
            if mistake['analysis_status']!='ready':
                raise HTTPException(409,'请先完成题目分析与确认。')
            practice_id=new_id()
            conn.execute('INSERT INTO practice_sessions(id,mistake_id,content_version,created_at) VALUES(?,?,?,?)',(practice_id,mistake['id'],mistake['content_version'],timestamp()))
            if daily_task_item_id:
                self.learning.bind_practice(conn,student,mistake,daily_task_item_id,practice_id)
            return {'id':practice_id,'mistake_id':mistake['id'],'content_version':mistake['content_version'],'hint_count':0}

    def request_hint(self, student, mistake_id, practice_id):
        import json
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            mistake=self.repository.get(conn,student,mistake_id)
            practice=conn.execute('SELECT * FROM practice_sessions WHERE id=? AND mistake_id=? AND content_version=?',(str(practice_id),mistake['id'],mistake['content_version'])).fetchone()
            if not practice:
                raise HTTPException(404,'练习不存在。')
            self.learning.validate_practice(conn,student,practice)
            if practice['consumed']:
                raise HTTPException(409,'练习已提交作答。')
            if practice['hint_count']>=10:
                raise HTTPException(409,'本次练习提示次数已达上限，请重新练习。')
            analysis=conn.execute('SELECT payload FROM analyses WHERE mistake_id=? AND content_version=? ORDER BY created_at DESC LIMIT 1',(mistake['id'],mistake['content_version'])).fetchone()
            if mistake['analysis_status']!='ready' or not analysis:
                raise HTTPException(409,'请先完成题目分析。')
            teaching_grade=mistake['grade'] if mistake['grade'] is not None else self.learning.get_preferences(conn,student).grade
            count=practice['hint_count']+1
            conn.execute('UPDATE practice_sessions SET hint_count=? WHERE id=?',(count,str(practice_id)))
        payload=json.loads(analysis['payload'])
        provider=getattr(self,'hint_provider',None)
        if provider:
            hint=provider(payload,count)
        else:
            from ..settings import Settings
            values={**self.settings.model_dump(),'grade':teaching_grade}
            with self.tutor_factory(Settings.model_validate(values)) as tutor:
                hint=tutor.chat('题目：'+payload['problem_text']+f'\n这是第{count}次提示，请给一个小提示帮助学生下一步思考。',mode='hint')
        return {'hint':hint,'hint_count':count,'practice_id':str(practice_id)}

    def submit_attempt(self, student, mistake_id, text, image, mime, practice_id, idempotency_key):
        import base64
        import json
        from datetime import timedelta
        from threading import Event, Thread
        from .models import utc_now
        from ..settings import Settings
        from .diagnosis import Judge
        if not text.strip() and image is None:
            raise HTTPException(422,'请提供答案文本或作答图片。')
        if image is not None:
            from ..images import load_image
            load_image(f'data:{mime};base64,'+base64.b64encode(image).decode())
        token=new_id()
        now=self.clock()
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            mistake=self.repository.get(conn,student,mistake_id)
            if mistake['analysis_status']!='ready':
                raise HTTPException(409,'当前题目尚无可用分析，请先分析或确认题干。')
            analysis=conn.execute('SELECT * FROM analyses WHERE mistake_id=? AND content_version=? ORDER BY created_at DESC LIMIT 1',(mistake['id'],mistake['content_version'])).fetchone()
            if not analysis:
                raise HTTPException(409,'分析记录不可用。')
            teaching_grade=mistake['grade'] if mistake['grade'] is not None else self.learning.get_preferences(conn,student).grade
            digest=hashlib.sha256(json.dumps([mistake['content_version'],text,hashlib.sha256(image).hexdigest() if image else None,mime,str(practice_id) if practice_id else None],ensure_ascii=False).encode()).hexdigest()
            prior=conn.execute('SELECT * FROM attempt_submissions WHERE mistake_id=? AND idempotency_key=?',(mistake['id'],idempotency_key)).fetchone()
            if prior:
                if prior['digest']!=digest:
                    raise HTTPException(409,'幂等键已经用于不同作答。')
                if prior['status']=='done':
                    return self.repository.attempt_dict(conn.execute('SELECT * FROM attempts WHERE id=?',(prior['attempt_id'],)).fetchone()),False
                if prior['status']=='processing' and prior['lease_until']>timestamp(now):
                    return {'submission_id':prior['id'],'status':'processing'},None
            practice=None
            if practice_id:
                practice=conn.execute('SELECT * FROM practice_sessions WHERE id=? AND mistake_id=? AND content_version=?',(str(practice_id),mistake['id'],mistake['content_version'])).fetchone()
                if not practice:
                    raise HTTPException(404,'练习不存在。')
                self.learning.validate_practice(conn,student,practice)
                same_submission=prior and prior['practice_id']==str(practice_id)
                if practice['consumed'] and not same_submission:
                    raise HTTPException(409,'这次练习已经提交。')
                conn.execute('UPDATE practice_sessions SET consumed=1 WHERE id=?',(str(practice_id),))
            if prior:
                submission_id=prior['id']
                conn.execute("UPDATE attempt_submissions SET status='processing',lease_token=?,lease_until=? WHERE id=?",(token,timestamp(now+timedelta(seconds=self.settings.job_lease_seconds)),submission_id))
            else:
                submission_id=new_id()
                conn.execute("INSERT INTO attempt_submissions(id,mistake_id,content_version,idempotency_key,digest,practice_id,status,lease_token,lease_until) VALUES(?,?,?,?,?,?,'processing',?,?)",(submission_id,mistake['id'],mistake['content_version'],idempotency_key,digest,str(practice_id) if practice_id else None,token,timestamp(now+timedelta(seconds=self.settings.job_lease_seconds))))
        stopped=Event()
        def heartbeat():
            while not stopped.wait(self.settings.job_lease_seconds/3):
                try:
                    with self.database.connect() as conn:
                        if not conn.execute("UPDATE attempt_submissions SET lease_until=? WHERE id=? AND lease_token=? AND status='processing'",(timestamp(utc_now()+timedelta(seconds=self.settings.job_lease_seconds)),submission_id,token)).rowcount:
                            return
                except Exception:
                    from ..logging import logger
                    logger.bind(event='attempt.renew_error',mistake_id=mistake['id']).warning('Submission lease renewal failed')
        thread=Thread(target=heartbeat,daemon=True)
        thread.start()
        stored=None
        try:
            values={**self.settings.model_dump(),'grade':teaching_grade}
            judge=getattr(self,'judge',None) or Judge(self.tutor_factory,Settings.model_validate(values))
            data_url=f'data:{mime};base64,'+base64.b64encode(image).decode() if image else None
            result=judge.judge(json.loads(analysis['payload']),text,data_url)
            if image:
                stored=self.storage.put(student.student_id,image,mime)
            with self.database.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                current=self.repository.get(conn,student,mistake_id)
                reserved=conn.execute("SELECT * FROM attempt_submissions WHERE id=? AND lease_token=? AND status='processing' AND lease_until>?",(submission_id,token,timestamp(self.clock()))).fetchone()
                if current['content_version']!=mistake['content_version'] or not reserved:
                    raise HTTPException(409,'题目或作答任务已变化，请重新提交。')
                asset_id=None
                if stored:
                    asset_id=new_id()
                    conn.execute("INSERT INTO assets(id,student_id,mistake_id,purpose,storage_key,mime,size,sha256) VALUES(?,?,?,'attempt',?,?,?,?)",(asset_id,str(student.student_id),mistake['id'],stored.storage_key,mime,stored.size,stored.sha256))
                attempt_id=new_id()
                hint_count=practice['hint_count'] if practice else 0
                independent=bool(practice and hint_count==0)
                conn.execute('INSERT INTO attempts(id,mistake_id,content_version,text,asset_id,status,hint_count,independent,evidence,diagnoses,created_at,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(attempt_id,mistake['id'],mistake['content_version'],text,asset_id,result.status,hint_count,int(independent),result.evidence,json.dumps([d.model_dump() for d in result.diagnoses],ensure_ascii=False),timestamp(self.clock()),idempotency_key))
                conn.execute('UPDATE attempts SET analysis_id=? WHERE id=?', (analysis['id'],attempt_id))
                conn.execute("UPDATE attempt_submissions SET status='done',attempt_id=?,lease_token=NULL,lease_until=NULL WHERE id=?",(attempt_id,submission_id))
                attempt=self.repository.attempt_dict(conn.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone())
                self.learning.validate_practice(conn,student,practice)
                self.update_review(conn,current,attempt,student)
                self.learning.apply_attempt(conn,student,practice_id,attempt)
                return attempt,True
        except Exception:
            if stored:
                self.storage.delete(stored.storage_key)
            with self.database.connect() as conn:
                conn.execute("UPDATE attempt_submissions SET status='failed',lease_token=NULL,lease_until=NULL WHERE id=? AND lease_token=?",(submission_id,token))
            raise
        finally:
            stopped.set()
            thread.join(timeout=2)

    def update_review(self, conn, mistake, attempt, student):
        import json
        from datetime import datetime
        from .review import ReviewState,ReviewPolicy
        row=conn.execute('SELECT * FROM review_schedules WHERE mistake_id=?',(mistake['id'],)).fetchone()
        state=ReviewState(learning_status=mistake['learning_status'])
        if row:
            state=ReviewState(stage=row['stage'],next_review_at=datetime.fromisoformat(row['next_review_at']),last_review_at=datetime.fromisoformat(row['last_review_at']) if row['last_review_at'] else None,correct_dates=tuple(json.loads(row['correct_dates'])),due_passed=bool(row['due_passed']),learning_status=mistake['learning_status'])
        decision=ReviewPolicy(self.settings.review_intervals).apply(state,attempt,self.clock(),self.learning.get_preferences(conn,student).timezone)
        new=decision.state
        if new!=state and new.next_review_at:
            conn.execute('INSERT INTO review_schedules(mistake_id,stage,next_review_at,last_review_at,correct_dates,due_passed) VALUES(?,?,?,?,?,?) ON CONFLICT(mistake_id) DO UPDATE SET stage=excluded.stage,next_review_at=excluded.next_review_at,last_review_at=excluded.last_review_at,correct_dates=excluded.correct_dates,due_passed=excluded.due_passed',(mistake['id'],new.stage,timestamp(new.next_review_at),timestamp(new.last_review_at) if new.last_review_at else None,json.dumps(new.correct_dates),int(new.due_passed)))
        conn.execute('UPDATE mistakes SET learning_status=?,updated_at=? WHERE id=?',(decision.learning_status,timestamp(self.clock()),mistake['id']))

    def correct_attempt(self, student, mistake_id, attempt_id, judgment, *, reason, actor_id):
        """Internal maintenance only: caller MUST authorize a verified teacher actor.

        No HTTP student route exposes this function. Keep original judgment in
        an append-only correction audit and rebuild only the current version.
        """
        import json
        from datetime import datetime
        from .diagnosis import Judgment
        from .review import ReviewState,ReviewPolicy
        judgment=Judgment.model_validate(judgment)
        if not reason.strip() or not actor_id.strip():
            raise ValueError('人工修正需要已验证的操作者和理由。')
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            mistake=self.repository.get(conn,student,mistake_id)
            original=conn.execute('SELECT * FROM attempts WHERE id=? AND mistake_id=?',(str(attempt_id),mistake['id'])).fetchone()
            if not original:
                raise HTTPException(404,'作答不存在。')
            snapshot=conn.execute('SELECT payload FROM analyses WHERE id=?',(original['analysis_id'],)).fetchone()
            payload=json.loads(snapshot['payload']) if snapshot else {}
            ids={p['id'] for p in [*payload.get('core_knowledge_points',[]),*payload.get('detailed_knowledge_points',[])]}
            steps={s['index'] for s in payload.get('steps',[])}
            if any(any(k not in ids for k in d.knowledge_point_ids) or (d.step_index is not None and d.step_index not in steps) for d in judgment.diagnoses):
                raise ValueError('人工修正引用了无效步骤或知识点。')
            conn.execute('INSERT INTO attempt_corrections(id,attempt_id,actor_id,reason,original_payload,corrected_payload,created_at) VALUES(?,?,?,?,?,?,?)',(new_id(),str(attempt_id),actor_id,reason,json.dumps(self.repository.attempt_dict(original),ensure_ascii=False),judgment.model_dump_json(),timestamp(self.clock())))
            conn.execute("UPDATE attempts SET status=?,evidence=?,diagnoses=?,provenance='human_confirmed' WHERE id=?",(judgment.status,judgment.evidence,json.dumps([d.model_dump() for d in judgment.diagnoses],ensure_ascii=False),str(attempt_id)))
            if original['content_version']==mistake['content_version']:
                state=ReviewState()
                policy=ReviewPolicy(self.settings.review_intervals)
                for row in conn.execute('SELECT * FROM attempts WHERE mistake_id=? AND content_version=? ORDER BY created_at,id',(mistake['id'],mistake['content_version'])):
                    state=policy.apply(state,self.repository.attempt_dict(row),datetime.fromisoformat(row['created_at']),self.learning.get_preferences(conn,student).timezone).state
                conn.execute('DELETE FROM review_schedules WHERE mistake_id=?',(mistake['id'],))
                if state.next_review_at:
                    conn.execute('INSERT INTO review_schedules(mistake_id,stage,next_review_at,last_review_at,correct_dates,due_passed) VALUES(?,?,?,?,?,?)',(mistake['id'],state.stage,timestamp(state.next_review_at),timestamp(state.last_review_at) if state.last_review_at else None,json.dumps(state.correct_dates),int(state.due_passed)))
                conn.execute('UPDATE mistakes SET learning_status=?,updated_at=? WHERE id=?',(state.learning_status,timestamp(self.clock()),mistake['id']))
            corrected=self.repository.attempt_dict(conn.execute('SELECT * FROM attempts WHERE id=?',(str(attempt_id),)).fetchone())
            submission=conn.execute('SELECT practice_id FROM attempt_submissions WHERE attempt_id=?',(str(attempt_id),)).fetchone()
            if submission:
                self.learning.apply_attempt(conn,student,submission['practice_id'],corrected)
            return corrected
