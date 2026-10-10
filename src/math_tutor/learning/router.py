"""Student-scoped learning endpoints; blocking database work runs in threadpool."""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Request
from ..mistakes.identity import get_student
from ..mistakes.models import StudentContext
from .schemas import LearningPreferences
from .models import DailyTask

router=APIRouter(prefix='/v1/learning',tags=['learning'])
Student=Annotated[StudentContext,Depends(get_student)]


@router.get('/abilities')
def abilities(request: Request, student: Student):
    return request.app.state.learning_service.abilities(student)


@router.get('/preferences',response_model=LearningPreferences)
def preferences(request: Request, student: Student):
    return request.app.state.learning_service.preferences(student)


@router.put('/preferences',response_model=LearningPreferences)
def update_preferences(request: Request, student: Student, body: LearningPreferences):
    return request.app.state.learning_service.update_preferences(student,body)


@router.post('/daily-tasks',status_code=201,response_model=DailyTask)
def generate(request: Request, student: Student):
    return request.app.state.learning_service.generate_today(student)


@router.get('/daily-tasks/today',response_model=DailyTask)
def today(request: Request, student: Student):
    return request.app.state.learning_service.today(student)


@router.get('/daily-tasks/{task_id}',response_model=DailyTask)
def task(request: Request, student: Student, task_id: UUID):
    return request.app.state.learning_service.get_task(student,str(task_id))
