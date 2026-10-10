import json
import pytest
from pydantic import ValidationError
from math_tutor.mistakes.diagnosis import Judgment, Judge
from math_tutor import MathTutor, Settings, TutorError
from test_tutor import backend
from test_analysis import analysis_data


def test_diagnosis_requires_evidence():
    with pytest.raises(ValidationError):
        Judgment(status='incorrect',evidence='',diagnoses=[])
    with pytest.raises(ValidationError):
        Judgment(status='correct',evidence='匹配',diagnoses=[{'category':'concept','evidence':'x','explanation':'x','knowledge_point_ids':[]}])


def test_judgment_uses_native_schema_and_validates_references(backend,analysis_data):
    client,requests,responses=backend
    responses[:]=[json.dumps({'status':'incorrect','evidence':'学生写了5','diagnoses':[{'category':'calculation','evidence':'24÷6=5','explanation':'计算结果错误','step_index':2,'knowledge_point_ids':['unknown']} ]})]
    judge=Judge(lambda s:MathTutor(client=client,settings=s),Settings(_env_file=None))
    with pytest.raises(TutorError):
        judge.judge(analysis_data,'5',None)
    assert 'responseJsonSchema' in requests[0]['generationConfig']
    assert 'responseSchema' not in requests[0]['generationConfig']


def test_exact_decimal_only():
    judge=Judge(lambda s:pytest.fail('model must not be called'),Settings(_env_file=None))
    result=judge.judge({'answer':'4'},'4.0',None)
    assert result.status=='correct'


from test_logging import records


def test_judgment_error_redacts_reference_and_student_work(backend,records,analysis_data):
    sdk,_,responses=backend
    analysis_data['problem_text']='需要保护的学生题干'
    responses[:]=[{'error':{'code':400,'message':'Invalid payload: 需要保护的学生题干; 学生私密作答; private-key'}}]
    settings=Settings(_env_file=None,api_key='private-key')
    judge=Judge(lambda s:MathTutor(client=sdk,settings=s),settings)
    with pytest.raises(TutorError):
        judge.judge(analysis_data,'学生私密作答',None)
    output=str(records)
    assert '需要保护的学生题干' not in output
    assert '学生私密作答' not in output
    assert 'private-key' not in output
