"""Trusted maintenance operations; never exposed through student routes."""
import json
from uuid import UUID
from fastapi import HTTPException
from ..mistakes.repository import Repository


class CatalogService:
    def __init__(self, database):
        self.database = database

    def put_point(self, point_id, name, parent_id, min_grade, max_grade):
        point_id = str(UUID(point_id))
        parent_id = str(UUID(parent_id)) if parent_id else None
        if not name.strip() or not 1 <= min_grade <= max_grade <= 12:
            raise ValueError('知识点名称或年级范围无效。')
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if parent_id:
                parent=conn.execute('SELECT parent_id FROM knowledge_points WHERE id=?',(parent_id,)).fetchone()
                if parent is None:
                    raise ValueError('父知识点不存在。')
                if parent['parent_id'] is not None or conn.execute('SELECT 1 FROM knowledge_points WHERE parent_id=? LIMIT 1',(point_id,)).fetchone():
                    raise ValueError('目录只支持核心与细分两级，不能创建三级或将有子节点的核心重挂。')
            ancestor = parent_id
            while ancestor:
                if ancestor == point_id:
                    raise ValueError('知识点不能形成循环。')
                row = conn.execute('SELECT parent_id FROM knowledge_points WHERE id=?', (ancestor,)).fetchone()
                if row is None:
                    raise ValueError('父知识点不存在。')
                ancestor = row['parent_id']
            current = conn.execute('SELECT parent_id FROM knowledge_points WHERE id=?', (point_id,)).fetchone()
            if current and current['parent_id'] != parent_id:
                used = conn.execute('SELECT 1 FROM mistake_knowledge_points WHERE knowledge_point_id=? LIMIT 1', (point_id,)).fetchone()
                if used:
                    raise ValueError('已映射知识点不能更改层级；请建立新节点。')
            conn.execute('''INSERT INTO knowledge_points VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,parent_id=excluded.parent_id,min_grade=excluded.min_grade,max_grade=excluded.max_grade''',
                (point_id,name.strip(),parent_id,min_grade,max_grade))

    def map_point(self, student, mistake_id, analysis_id, local_id, point_id):
        point_id = str(UUID(point_id))
        with self.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            Repository(self.database).get(conn,student,mistake_id)
            row = conn.execute('SELECT payload FROM analyses WHERE id=? AND mistake_id=?', (str(analysis_id),str(mistake_id))).fetchone()
            if row is None:
                raise HTTPException(404,'分析不存在。')
            payload = json.loads(row['payload'])
            cores = {p['id'] for p in payload.get('core_knowledge_points',[])}
            details = {p['id'] for p in payload.get('detailed_knowledge_points',[])}
            if local_id not in cores | details:
                raise HTTPException(404,'局部知识点不存在。')
            point = conn.execute('SELECT parent_id FROM knowledge_points WHERE id=?', (point_id,)).fetchone()
            if point is None:
                raise ValueError('全局知识点不存在。')
            if point['parent_id']:
                parent=conn.execute('SELECT parent_id FROM knowledge_points WHERE id=?',(point['parent_id'],)).fetchone()
                if parent is None or parent['parent_id'] is not None:
                    raise ValueError('目录只支持核心与细分两级映射。')
            if (local_id in cores) != (point['parent_id'] is None):
                raise ValueError('核心与细分知识点层级不匹配。')
            conn.execute('''INSERT INTO mistake_knowledge_points VALUES(?,?,?,'confirmed')
                ON CONFLICT(analysis_id,local_id) DO UPDATE SET knowledge_point_id=excluded.knowledge_point_id,mapping_status='confirmed' ''',
                (str(analysis_id),local_id,point_id))
