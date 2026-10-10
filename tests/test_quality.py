import json
import pytest
from math_tutor import MathTutor,ProblemAnalysis,Settings
from math_tutor.quality import check_analysis,evaluate_numeric
from test_tutor import backend
from test_analysis import analysis_data


@pytest.mark.parametrize('expression,expected',[('24÷6',4),('(-2)+(-1)+0+1+3+4+5',10),('0.1+0.2',0.3),('2×(3+4)',14),('1/3+2/3',1)])
def test_numeric_evaluation(expression,expected):
    from fractions import Fraction
    assert evaluate_numeric(expression)==Fraction(str(expected))


@pytest.mark.parametrize('expression',["__import__('os').system('echo bad')",'x+1','1/0','2**100000','9'*1000,'[1,2]','sum([1])'])
def test_unsupported_or_dangerous_input_not_executed(expression):
    assert evaluate_numeric(expression) is None


def test_wrong_arithmetic_is_repairable_and_exact_decimals_pass(analysis_data):
    analysis_data['steps'][1]['formula']='24÷6=5'
    report=check_analysis(ProblemAnalysis.model_validate(analysis_data))
    assert report.status=='needs_repair'
    assert report.issues[0].code=='arithmetic_error'
    assert report.issues[0].step_index==2
    analysis_data['steps'][1]['formula']='0.1+0.2=0.3'
    assert check_analysis(ProblemAnalysis.model_validate(analysis_data)).status=='passed'


def test_symbolic_formulas_require_review_without_claiming_false(analysis_data):
    analysis_data['steps'][0]['formula']='x=(6-a)/4'
    report=check_analysis(ProblemAnalysis.model_validate(analysis_data))
    assert report.status=='passed'
    assert report.requires_model_review
    assert report.unchecked_formulas>0


def test_rational_equation_checks_domain_before_transformation(analysis_data):
    analysis_data['problem_text']='求分式方程 2/(x-1)=4 的解。'
    analysis_data['steps'][0]['formula']='2/(x-1)=4'
    report=check_analysis(ProblemAnalysis.model_validate(analysis_data))
    assert any(issue.code=='missing_domain' for issue in report.issues)
    analysis_data['steps'][0]['description']='先写明 x-1≠0，再求解方程。'
    report=check_analysis(ProblemAnalysis.model_validate(analysis_data))
    assert not any(issue.code=='missing_domain' for issue in report.issues)


def test_non_solved_result_does_not_invent_checks():
    result=ProblemAnalysis(status='needs_clarification',problem_text='数字不清',core_knowledge_points=[],detailed_knowledge_points=[],steps=[],answer=None,clarifications=['请确认数字'])
    report=check_analysis(result)
    assert report.status=='needs_confirmation'
    assert report.checked_equalities==0


def test_numeric_error_gets_one_repair_and_never_changes_history(backend,analysis_data):
    sdk,requests,responses=backend
    incorrect={**analysis_data,'steps':[dict(step) for step in analysis_data['steps']]}
    incorrect['steps'][1]['formula']='24÷6=5'
    responses[:]=[json.dumps(incorrect),json.dumps(analysis_data)]
    tutor=MathTutor(client=sdk,settings=Settings(_env_file=None))
    result=tutor.analyze_problem('题目')
    assert result.status=='solved'
    assert result.steps[1].formula=='24÷6=4'
    assert len(requests)==2
    assert tutor.turn_count==0


def test_repeated_quality_error_returns_clarification_without_bad_answer(backend,analysis_data):
    sdk,requests,responses=backend
    analysis_data['steps'][1]['formula']='24÷6=5'
    responses[:]=[json.dumps(analysis_data)]*3
    result=MathTutor(client=sdk,settings=Settings(_env_file=None)).analyze_problem('题目')
    assert len(requests)==2
    assert result.status=='needs_clarification'
    assert result.answer is None and result.steps==[]


def test_risk_review_schema_and_issue_triggers_repair(backend,analysis_data):
    sdk,requests,responses=backend
    analysis_data['steps'][0]['formula']='x=(6-a)/4'
    review_bad={'status':'needs_repair','issues':[{'code':'missing_condition','step_index':1,'message':'缺少成立条件。'}]}
    review_good={'status':'passed','issues':[]}
    responses[:]=[json.dumps(analysis_data),json.dumps(review_bad),json.dumps(analysis_data),json.dumps(review_good)]
    result=MathTutor(client=sdk,settings=Settings(_env_file=None)).analyze_problem('含参题目')
    assert result.status=='solved'
    assert len(requests)==4
    assert 'responseJsonSchema' in requests[1]['generationConfig']
    assert 'responseSchema' not in requests[1]['generationConfig']


def test_review_failure_or_ambiguity_avoids_unverified_solution(backend,analysis_data):
    sdk,requests,responses=backend
    analysis_data['steps'][0]['formula']='x=(6-a)/4'
    responses[:]=[json.dumps(analysis_data),503]
    result=MathTutor(client=sdk,settings=Settings(_env_file=None)).analyze_problem('含参题目')
    assert result.status=='needs_clarification'
    assert result.answer is None
    assert len(requests)==2


def test_review_can_be_off_without_disabling_arithmetic_checks(backend,analysis_data):
    sdk,requests,responses=backend
    analysis_data['steps'][0]['formula']='x=(6-a)/4'
    responses[:]=[json.dumps(analysis_data)]
    result=MathTutor(client=sdk,settings=Settings(_env_file=None,quality_model_review='off')).analyze_problem('题目')
    assert result.status=='solved' and len(requests)==1


@pytest.mark.parametrize('expression,expected',[(r'\frac{24}{6}',4),(r'\frac{1}{\frac{2}{3}}',1.5),(r'\left(2+3\right)\times 4',20)])
def test_numeric_latex_is_checked_without_model(expression,expected):
    from fractions import Fraction
    assert evaluate_numeric(expression)==Fraction(str(expected))


def test_numeric_final_answer_mismatch_is_detected(analysis_data):
    analysis_data['answer']='5'
    report=check_analysis(ProblemAnalysis.model_validate(analysis_data))
    assert report.status=='needs_repair'
    assert any(issue.code=='answer_mismatch' for issue in report.issues)


def test_quality_settings_load_from_env_and_limit_repairs(monkeypatch):
    monkeypatch.setenv('TUTOR_QUALITY_MAX_REPAIRS','0')
    monkeypatch.setenv('TUTOR_QUALITY_MODEL_REVIEW','always')
    settings=Settings(_env_file=None)
    assert settings.quality_max_repairs==0
    assert settings.quality_model_review=='always'
    for value in (2,True,1.0):
        with pytest.raises(ValueError):
            Settings(_env_file=None,quality_max_repairs=value)


def test_zero_repairs_stops_after_initial_bad_calculation(backend,analysis_data):
    sdk,requests,responses=backend
    analysis_data['steps'][1]['formula']='24÷6=5'
    responses[:]=[json.dumps(analysis_data)]
    result=MathTutor(client=sdk,settings=Settings(_env_file=None,quality_max_repairs=0)).analyze_problem('题目')
    assert result.status=='needs_clarification' and len(requests)==1


def test_invalid_review_references_do_not_accept_answer(backend,analysis_data):
    sdk,requests,responses=backend
    analysis_data['steps'][0]['formula']='x=(6-a)/4'
    responses[:]=[json.dumps(analysis_data),json.dumps({'status':'needs_repair','issues':[{'code':'missing_condition','step_index':99,'message':'错误的步骤引用'}]})]
    result=MathTutor(client=sdk,settings=Settings(_env_file=None)).analyze_problem('题目')
    assert result.status=='needs_clarification' and len(requests)==2


def test_erasing_formulas_cannot_bypass_quality_check(analysis_data):
    for step in analysis_data['steps']:
        step['formula']=None
    analysis_data['steps'][1]['description']='计算24÷6=5。'
    analysis_data['answer']='5'
    report=check_analysis(ProblemAnalysis.model_validate(analysis_data))
    assert report.status!='passed' or report.requires_model_review
    assert any(issue.code=='missing_formula' for issue in report.issues)


def test_repair_keeps_review_requirement_if_candidate_simplifies_risk(backend,analysis_data):
    sdk,requests,responses=backend
    risky={**analysis_data,'steps':[dict(s) for s in analysis_data['steps']]}
    risky['steps'][0]['formula']='x=(6-a)/4'
    review_bad={'status':'needs_repair','issues':[{'code':'missing_condition','step_index':1,'message':'缺少条件'}]}
    review_confirm={'status':'needs_confirmation','issues':[{'code':'unverified','message':'暂无法核验修复结果'}]}
    responses[:]=[json.dumps(risky),json.dumps(review_bad),json.dumps(analysis_data),json.dumps(review_confirm)]
    result=MathTutor(client=sdk,settings=Settings(_env_file=None)).analyze_problem('题目')
    assert len(requests)==4
    assert result.status=='needs_clarification' and result.answer is None


def test_copying_original_equation_before_domain_is_not_transformation(analysis_data):
    analysis_data['problem_text']='求分式方程 2/(x-1)=4 的解'
    analysis_data['steps'][0]['description']='先抄写题目给出的原方程。'
    analysis_data['steps'][0]['formula']='2/(x-1)=4'
    analysis_data['steps'][1]['description']='开始运算前列出分母非零条件。'
    analysis_data['steps'][1]['formula']='x-1≠0'
    report=check_analysis(ProblemAnalysis.model_validate(analysis_data))
    assert not any(issue.code=='missing_domain' for issue in report.issues)
    assert report.requires_model_review
