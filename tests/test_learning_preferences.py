from uuid import uuid4
import pytest
from math_tutor.mistakes.database import Database
from math_tutor.mistakes.models import StudentContext


def test_preferences_defaults_and_persistence(tmp_path):
    from math_tutor.learning.repository import LearningRepository
    from math_tutor.learning.schemas import LearningPreferences
    db=Database(tmp_path/'db'); db.migrate()
    repo=LearningRepository(db); student=StudentContext(uuid4(),'Europe/London')
    with db.connect() as conn:
        value=repo.get_preferences(conn,student)
        assert value.timezone=='Europe/London' and value.daily_limit==5
        assert value.grade is None and not value.daily_enabled and value.generation_time=='19:00'
        repo.save_preferences(conn,student,LearningPreferences(grade=11,timezone='Asia/Shanghai',daily_limit=3),None)
    with db.connect() as conn:
        assert repo.get_preferences(conn,student).grade==11
        assert repo.get_preferences(conn,StudentContext(uuid4())).grade is None


@pytest.mark.parametrize('values',[{'timezone':'bad/zone'},{'generation_time':'9:00'},{'generation_time':'24:00'},{'daily_limit':0},{'daily_limit':11},{'grade':13},{'grade':True}])
def test_preferences_reject_invalid_values(values):
    from math_tutor.learning.schemas import LearningPreferences
    with pytest.raises(ValueError): LearningPreferences(**values)
