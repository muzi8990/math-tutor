"""Trusted server-side maintenance and scheduling entry point."""
import argparse
from uuid import UUID
from ..settings import Settings
from ..mistakes.database import Database
from ..mistakes.models import StudentContext
from .catalog import CatalogService


def main(argv=None):
    parser=argparse.ArgumentParser(description='学习目录维护和每日任务调度（仅受信任服务端操作员）')
    parser.add_argument('--env-file',default='.env')
    commands=parser.add_subparsers(dest='command',required=True)
    put=commands.add_parser('catalog-put')
    put.add_argument('--id',type=UUID,required=True)
    put.add_argument('--name',required=True)
    put.add_argument('--parent-id',type=UUID)
    put.add_argument('--min-grade',type=int,required=True)
    put.add_argument('--max-grade',type=int,required=True)
    mapping=commands.add_parser('catalog-map')
    for name in ['student-id','mistake-id','analysis-id','point-id']:
        mapping.add_argument('--'+name,type=UUID,required=True)
    mapping.add_argument('--local-id',required=True)
    commands.add_parser('scheduler')
    args=parser.parse_args(argv)
    try:
        settings=Settings(_env_file=args.env_file)
        db=Database(settings.database_path); db.migrate()
        service=CatalogService(db)
        if args.command=='scheduler':
            return run_scheduler(db,settings)
        if args.command=='catalog-put':
            service.put_point(str(args.id),args.name,str(args.parent_id) if args.parent_id else None,args.min_grade,args.max_grade)
        else:
            service.map_point(StudentContext(args.student_id),str(args.mistake_id),str(args.analysis_id),args.local_id,str(args.point_id))
    except Exception:
        # Never echo SQL, question payload, environment or exception input.
        parser.exit(1,'维护操作失败，请检查参数、记录和数据库。\n')
    return 0


def run_scheduler(database, settings):
    import signal
    from threading import Event
    from ..logging import configure_logging, remove_handlers, logger
    from .scheduler import LearningScheduler
    stopped=Event()
    old_handlers={number:signal.getsignal(number) for number in (signal.SIGINT,signal.SIGTERM)}
    def stop(*_):
        stopped.set()
    for number in old_handlers:
        signal.signal(number,stop)
    handlers=configure_logging(settings)
    try:
        scheduler=LearningScheduler(database)
        logger.bind(event='learning.scheduler_start').info('Learning scheduler started')
        while not stopped.is_set():
            try:
                scheduler.run_once()
            except Exception:
                logger.bind(event='learning.scheduler_database_error').error('Learning database unavailable; retry on next scan')
            stopped.wait(60)
        logger.bind(event='learning.scheduler_stop').info('Learning scheduler stopped')
    finally:
        for number,handler in old_handlers.items():
            signal.signal(number,handler)
        remove_handlers(handlers)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
