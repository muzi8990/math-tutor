"""Private original-image storage; normalized copies only go to the model."""
import base64
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..images import MIME_TYPES, load_image


@dataclass(frozen=True)
class StoredAsset:
    storage_key: str
    mime: str
    size: int
    sha256: str


class AssetStorage:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, key):
        if not re.fullmatch(r'[0-9a-f-]{36}/[0-9a-f-]{36}', key):
            raise ValueError('无效资源标识。')
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('无效资源路径。')
        return path

    def put(self, student_id, raw, mime):
        if mime not in MIME_TYPES:
            raise ValueError('不支持的图片类型。')
        load_image(f'data:{mime};base64,' + base64.b64encode(raw).decode())
        key = f'{student_id}/{uuid4()}'
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return StoredAsset(key, mime, len(raw), hashlib.sha256(raw).hexdigest())

    def read(self, key):
        return self.path(key).read_bytes()

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)

    def sweep_orphans(self, database, now, *, minimum_age_seconds=86400):
        """Reclaim interrupted writes, excluding recent writes and referenced files."""
        from ..logging import logger
        cutoff=now.timestamp()-minimum_age_seconds
        with database.connect() as conn:
            referenced={row[0] for row in conn.execute('SELECT storage_key FROM assets')}
            referenced.update(row[0] for row in conn.execute('SELECT storage_key FROM cleanup_jobs'))
        removed=0
        for path in self.root.glob('*/*'):
            try:
                if path.is_symlink() or not path.is_file() or path.stat().st_mtime>=cutoff:
                    continue
                relative=path.relative_to(self.root).as_posix()
                key=relative.removesuffix('.tmp')
                if key in referenced or self.path(key).parent!=path.parent:
                    continue
                path.unlink(missing_ok=True)
                removed+=1
            except (OSError,ValueError):
                logger.bind(event='asset.orphan_cleanup_error').warning('Orphan image cleanup could not complete')
        return removed
