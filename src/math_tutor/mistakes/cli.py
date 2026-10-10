"""Run durable mistake-analysis workers independently from the API."""
import signal
from threading import Event, Thread
from time import monotonic
from ..agent import MathTutor
from ..settings import Settings
from ..logging import configure_logging, remove_handlers, logger
from .database import Database
from .storage import AssetStorage
from .service import MistakeService
from .worker import AnalysisWorker
from .models import utc_now


def finish_threads(threads, timeout):
    deadline = monotonic() + timeout
    for thread in threads:
        thread.join(max(0, deadline - monotonic()))
    return sum(thread.is_alive() for thread in threads)


def main():
    config = Settings()
    if config.api_key is None:
        raise SystemExit('请先设置 GOOGLE_API_KEY 或 GEMINI_API_KEY。')
    handlers = configure_logging(config)
    database = Database(config.database_path)
    database.migrate()
    storage = AssetStorage(config.asset_dir)
    storage.sweep_orphans(database, utc_now())
    service = MistakeService(database,storage,config,lambda s: MathTutor(settings=s))
    stopped = Event()
    def stop(*_): stopped.set()
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    def run():
        worker = AnalysisWorker(service)
        while not stopped.is_set():
            try:
                busy = worker.run_once()
            except Exception:
                logger.bind(event='worker.loop_error').error('Worker loop failed; retrying')
                busy = False
            if not busy:
                stopped.wait(1)
    try:
        # Daemon workers let a stuck provider call expire by lease after the
        # explicit shutdown deadline; executor threads would prevent exit.
        threads = [Thread(target=run, daemon=True) for _ in range(config.worker_concurrency)]
        for thread in threads:
            thread.start()
        stopped.wait()
        remaining = finish_threads(threads, min(config.timeout_ms / 1000 + 5, 30))
        if remaining:
            logger.bind(event='worker.shutdown_timeout', pending=remaining).warning('Shutdown deadline reached; unfinished jobs will recover by lease')
    finally:
        remove_handlers(handlers)


if __name__=='__main__':
    main()
