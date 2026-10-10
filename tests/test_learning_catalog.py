from uuid import uuid4
import pytest
from fastapi import HTTPException
from math_tutor.mistakes.database import Database
from test_mistake_attempts import ready
from test_mistake_api import mistake_client
from test_analysis import analysis_data


def test_catalog_hierarchy_and_distinct_names(tmp_path):
    from math_tutor.learning.catalog import CatalogService
    db=Database(tmp_path/'db'); db.migrate(); service=CatalogService(db)
    p,c,h=map(str,[uuid4(),uuid4(),uuid4()])
    service.put_point(p,'方程',None,1,6)
    service.put_point(c,'方程',p,1,6)
    service.put_point(h,'方程',None,7,9)
    with pytest.raises(ValueError): service.put_point(p,'方程',c,1,6)
    with pytest.raises(ValueError): service.put_point(str(uuid4()),'x',str(uuid4()),1,6)
    with pytest.raises(ValueError): service.put_point(p,'方程',None,7,6)
    with db.connect() as conn: assert conn.execute('SELECT count(*) FROM knowledge_points').fetchone()[0]==3


def test_mapping_requires_owner_local_node_and_level(ready):
    from math_tutor.learning.catalog import CatalogService
    from math_tutor.mistakes.models import StudentContext
    client,app,record=ready
    student=app.dependency_overrides[__import__('math_tutor.mistakes.identity',fromlist=['get_student']).get_student]()
    service=CatalogService(app.state.mistake_service.database)
    core,detail=map(str,[uuid4(),uuid4()])
    service.put_point(core,'平均分',None,1,6); service.put_point(detail,'除法',core,1,6)
    data=client.get('/v1/mistakes/'+record['id']).json(); aid=data['analysis_id']
    service.map_point(student,record['id'],aid,'K1',core)
    service.map_point(student,record['id'],aid,'K1.1',detail)
    with pytest.raises((ValueError,HTTPException)): service.map_point(student,record['id'],aid,'K1.1',core)
    with pytest.raises(HTTPException): service.map_point(StudentContext(uuid4()),record['id'],aid,'K1',core)
    with pytest.raises(HTTPException): service.map_point(student,record['id'],aid,'missing',detail)


def test_catalog_rejects_third_level_and_root_reparent(tmp_path):
    from math_tutor.learning.catalog import CatalogService
    db=Database(tmp_path/'db');db.migrate();service=CatalogService(db)
    root,detail,leaf,other=map(str,[uuid4(),uuid4(),uuid4(),uuid4()])
    service.put_point(root,'方程',None,7,9)
    service.put_point(detail,'分式方程',root,7,9)
    service.put_point(other,'代数',None,7,9)
    with pytest.raises(ValueError,match='两级'):
        service.put_point(leaf,'定义域',detail,7,9)
    with pytest.raises(ValueError,match='两级'):
        service.put_point(root,'方程',other,7,9)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM knowledge_points').fetchone()[0]==3
        assert conn.execute('SELECT parent_id FROM knowledge_points WHERE id=?',(root,)).fetchone()[0] is None


def test_mapping_rejects_legacy_third_level(ready):
    from math_tutor.learning.catalog import CatalogService
    from math_tutor.mistakes.identity import get_student
    client,app,record=ready
    service=CatalogService(app.state.mistake_service.database)
    root,detail,leaf=map(str,[uuid4(),uuid4(),uuid4()])
    service.put_point(root,'方程',None,7,9)
    service.put_point(detail,'分式方程',root,7,9)
    with app.state.mistake_service.database.connect() as conn:
        conn.execute('INSERT INTO knowledge_points VALUES(?,?,?,?,?)',(leaf,'定义域',detail,7,9))
    data=client.get('/v1/mistakes/'+record['id']).json()
    with pytest.raises(ValueError,match='两级'):
        service.map_point(app.dependency_overrides[get_student](),record['id'],data['analysis_id'],'K1.1',leaf)
