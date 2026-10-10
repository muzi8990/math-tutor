from datetime import datetime
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from ..images import MAX_IMAGE_BYTES, MIME_TYPES
from .identity import get_student
from .models import StudentContext
from .schemas import AnalysisStatus, LearningStatus

router = APIRouter(prefix='/v1/mistakes', tags=['错题管理'])
Student = Annotated[StudentContext, Depends(get_student)]


def get_service(request: Request):
    return request.app.state.mistake_service


async def read_upload(image):
    if image.content_type not in MIME_TYPES:
        raise HTTPException(415,'仅支持 PNG、JPEG 或 WebP。')
    try:
        raw = await image.read(MAX_IMAGE_BYTES+1)
    finally:
        await image.close()
    if len(raw)>MAX_IMAGE_BYTES:
        raise HTTPException(413,'图片超过 10 MiB。')
    return raw, image.content_type


async def validate_form(request, allowed):
    form = await request.form()
    keys = [key for key, _ in form.multi_items()]
    if set(keys) - set(allowed) or len(keys) != len(set(keys)):
        raise HTTPException(422, '表单包含未知或重复字段。')


@router.post('',status_code=201)
async def create(request: Request, student: Student, image: Annotated[UploadFile,File()], text: Annotated[str,Form(max_length=20_000)]='', grade: Annotated[int|None,Form(ge=1,le=6)]=None, note: Annotated[str,Form(max_length=2000)]='', allow_duplicate: Annotated[bool,Form()]=False):
    await validate_form(request, {'image','text','grade','note','allow_duplicate'})
    raw,mime = await read_upload(image)
    return await run_in_threadpool(get_service(request).create,student,raw,mime,text,grade,note,allow_duplicate)


@router.get('')
def list_mistakes(request: Request, student: Student, learning_status: LearningStatus|None=None, analysis_status: AnalysisStatus|None=None, knowledge_point_id: UUID|None=None, created_from: datetime|None=None, created_to: datetime|None=None, cursor: str|None=Query(None,max_length=1000), limit: int=Query(20,ge=1,le=100)):
    if any(d is not None and d.tzinfo is None for d in (created_from,created_to)):
        raise HTTPException(422,'日期需要包含时区。')
    if created_from and created_to and created_from>created_to:
        raise HTTPException(422,'日期范围无效。')
    return get_service(request).list(student,{'learning_status':learning_status,'analysis_status':analysis_status,'knowledge_point_id':knowledge_point_id,'created_from':created_from,'created_to':created_to},cursor,limit)


@router.get('/{mistake_id}')
def detail(request: Request,student: Student,mistake_id: UUID,include_solution: bool=False):
    return get_service(request).get(student,mistake_id,include_solution)


@router.get('/{mistake_id}/assets/{asset_id}')
def asset(request: Request,student: Student,mistake_id: UUID,asset_id: UUID):
    raw,mime = get_service(request).read_asset(student,mistake_id,asset_id)
    return Response(raw,media_type=mime,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.post('/{mistake_id}/analyze',status_code=202)
def analyze(request: Request,student: Student,mistake_id: UUID):
    return get_service(request).enqueue_analysis(student,mistake_id)


from .schemas import MistakePatch


@router.patch('/{mistake_id}')
def update(request: Request,student: Student,mistake_id: UUID,body: MistakePatch):
    return get_service(request).update(student,mistake_id,body)


@router.delete('/{mistake_id}',status_code=204)
def delete(request: Request,student: Student,mistake_id: UUID):
    get_service(request).delete(student,mistake_id)
    return Response(status_code=204)


from fastapi import Header
from fastapi.responses import JSONResponse


@router.post('/{mistake_id}/practice-sessions',status_code=201)
def practice(request: Request,student: Student,mistake_id: UUID):
    return get_service(request).create_practice(student,mistake_id)


@router.post('/{mistake_id}/practice-sessions/{practice_id}/hints')
def hint(request: Request,student: Student,mistake_id: UUID,practice_id: UUID):
    return get_service(request).request_hint(student,mistake_id,practice_id)


@router.post('/{mistake_id}/attempts',status_code=201)
async def attempt(request: Request,student: Student,mistake_id: UUID,idempotency_key: Annotated[str,Header(min_length=1,max_length=128)],text: Annotated[str,Form(max_length=20_000)]='',image: Annotated[UploadFile|None,File()]=None,practice_id: Annotated[UUID|None,Form()]=None):
    await validate_form(request, {'text','image','practice_id'})
    raw,mime=await read_upload(image) if image is not None else (None,None)
    result,created=await run_in_threadpool(get_service(request).submit_attempt,student,mistake_id,text,raw,mime,practice_id,idempotency_key)
    return JSONResponse(result,status_code=201 if created else 202 if created is None else 200)
