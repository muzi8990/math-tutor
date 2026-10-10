"""Shared K12 grade semantics; an absent grade is never inferred."""
from typing import Annotated
from pydantic import Field

Grade = Annotated[int, Field(ge=1, le=12, strict=True)]


def grade_description(grade: int | None) -> str:
    if grade is None:
        return '学生年级未知；采用题目所需的方法，教学方法确实依赖学段时询问年级。'
    if not 1 <= grade <= 12:
        raise ValueError('年级必须为 1–12。')
    numerals = ('一', '二', '三', '四', '五', '六')
    stage, year = ('小学', grade) if grade <= 6 else (('初中', grade - 6) if grade <= 9 else ('高中', grade - 9))
    label = str(year) if stage == '小学' else numerals[year - 1]
    return f'学生为{stage}{label}年级。'
