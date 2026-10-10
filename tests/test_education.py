import pytest
from pydantic import ValidationError
from math_tutor.settings import Settings
from math_tutor.api import AnalyzeRequest
from math_tutor.prompts import build_prompt


@pytest.mark.parametrize('grade',[7,9,10,12])
def test_k12_grade_is_accepted(grade):
    assert Settings(_env_file=None, grade=grade).grade == grade
    assert AnalyzeRequest(text='解方程', grade=grade).grade == grade


@pytest.mark.parametrize('grade',[0,13,True,1.5])
def test_invalid_grade_is_rejected(grade):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, grade=grade)
    with pytest.raises(ValidationError):
        AnalyzeRequest(text='题目', grade=grade)


def test_prompt_uses_student_stage():
    assert '初中一年级' in build_prompt('hint', 7)
    assert '高中三年级' in build_prompt('solve', 12)
    assert '小学' not in build_prompt('hint', None)
