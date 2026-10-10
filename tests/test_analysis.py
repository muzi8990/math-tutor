import copy
import json

import pytest
from pydantic import ValidationError

from math_tutor import MathTutor, ProblemAnalysis, TutorError
from math_tutor import cli
from test_tutor import backend, picture  # noqa: F401


@pytest.fixture
def analysis_data():
    return {
        'status': 'solved', 'problem_text': '24块饼干平均放入6个袋子，每袋几块？',
        'core_knowledge_points': [{'id': 'K1', 'name': '除法的意义', 'description': '把总量平均分成若干份。'}],
        'detailed_knowledge_points': [{'id': 'K1.1', 'parent_id': 'K1', 'name': '平均分求每份数量', 'description': '每份数量=总数量÷份数。'}],
        'steps': [
            {'index': 1, 'description': '共有24块，平均分成6份，需要求每份数量。', 'formula': '24÷6', 'knowledge_point_ids': ['K1', 'K1.1'], 'knowledge_application': '根据平均分的关系选择除法。'},
            {'index': 2, 'description': '计算并写出单位。', 'formula': '24÷6=4', 'knowledge_point_ids': [], 'knowledge_application': '此处不另行标注知识点。'},
        ],
        'answer': '每袋4块。', 'clarifications': [],
    }


def test_analysis_uses_json_schema_and_keeps_history_separate(backend, picture, analysis_data):
    client, requests, responses = backend
    responses[:] = [json.dumps(analysis_data, ensure_ascii=False)]
    tutor = MathTutor(client=client, grade=3)
    result = tutor.analyze_problem('请分析这道题', image=picture)
    assert result.core_knowledge_points[0].name == '除法的意义'
    assert result.detailed_knowledge_points[0].parent_id == 'K1'
    assert result.steps[0].knowledge_point_ids == ['K1', 'K1.1']
    assert result.answer == '每袋4块。'
    assert tutor.turn_count == 0
    config = requests[0]['generationConfig']
    assert config['responseMimeType'] == 'application/json'
    assert 'responseSchema' not in config
    schema = config['responseJsonSchema']
    assert schema == ProblemAnalysis.model_json_schema()
    assert schema['additionalProperties'] is False
    assert all(definition['additionalProperties'] is False for definition in schema['$defs'].values())
    assert 'additional_properties' not in json.dumps(schema)
    assert 'inlineData' in requests[0]['contents'][0]['parts'][1]


def test_unclear_problem_returns_no_invented_solution(backend):
    client, _, responses = backend
    responses[:] = [json.dumps({
        'status': 'needs_clarification', 'problem_text': '数字不清',
        'core_knowledge_points': [], 'detailed_knowledge_points': [], 'steps': [],
        'answer': None, 'clarifications': ['请确认总量是24还是29。'],
    })]
    result = MathTutor(client=client).analyze_problem('条件缺失的题')
    assert result.answer is None and result.steps == []
    assert result.clarifications


def test_analysis_rejects_unexpected_nested_fields(backend, analysis_data):
    client, _, responses = backend
    analysis_data['steps'][0]['unexpected'] = 'extra'
    responses[:] = [json.dumps(analysis_data)]
    with pytest.raises(TutorError):
        MathTutor(client=client).analyze_problem('题目')


@pytest.mark.parametrize('kind', ['unknown_parent', 'unknown_step_point', 'duplicate_id', 'bad_step_index', 'empty_answer', 'false_solution'])
def test_invalid_relationships_are_rejected(analysis_data, kind):
    data = copy.deepcopy(analysis_data)
    if kind == 'unknown_parent': data['detailed_knowledge_points'][0]['parent_id'] = 'unknown'
    elif kind == 'unknown_step_point': data['steps'][0]['knowledge_point_ids'] = ['unknown']
    elif kind == 'duplicate_id': data['detailed_knowledge_points'][0]['id'] = 'K1'
    elif kind == 'bad_step_index': data['steps'][1]['index'] = 3
    elif kind == 'empty_answer': data['answer'] = ' '
    elif kind == 'false_solution': data['status'] = 'needs_clarification'
    with pytest.raises(ValidationError):
        ProblemAnalysis.model_validate(data)


@pytest.mark.parametrize('output', ['not json', '{}'])
def test_malformed_analysis_reports_error_without_history(backend, output):
    client, _, responses = backend
    responses[:] = [output]
    tutor = MathTutor(client=client)
    with pytest.raises(TutorError):
        tutor.analyze_problem('题目')
    assert tutor.turn_count == 0


def test_cli_prints_structured_json(backend, analysis_data, monkeypatch, capsys):
    client, _, responses = backend
    responses[:] = [json.dumps(analysis_data)]
    monkeypatch.setattr(cli, 'MathTutor', lambda **kw: MathTutor(client=client, **kw))
    assert cli.main(['题目', '--analyze', '--env-file', '/nonexistent/test.env']) == 0
    assert json.loads(capsys.readouterr().out)['steps'][0]['knowledge_point_ids'] == ['K1', 'K1.1']


def test_cli_analysis_and_chat_are_mutually_exclusive():
    with pytest.raises(SystemExit) as exc:
        cli.main(['题目', '--analyze', '--chat'])
    assert exc.value.code == 2
