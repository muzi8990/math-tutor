import os
from pathlib import Path
import signal
import subprocess
import selectors
from uuid import uuid4


def command(envfile,*args):
    import sys
    env={**os.environ,'PYTHONPATH':str(Path('src').resolve())}
    return [sys.executable,'-m','math_tutor.learning.cli','--env-file',str(envfile),*args],env


def test_scheduler_starts_without_key_and_stops_on_signal(tmp_path):
    envfile=tmp_path/'test.env'
    envfile.write_text(f'TUTOR_DATABASE_PATH={tmp_path / "db"}\nTUTOR_LOG_FILE={tmp_path / "scheduler.log"}\n')
    argv,env=command(envfile,'scheduler')
    env.pop('GOOGLE_API_KEY',None); env.pop('GEMINI_API_KEY',None)
    process=subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        selector=selectors.DefaultSelector();selector.register(process.stderr,selectors.EVENT_READ)
        assert selector.select(timeout=10),'scheduler did not start'
        line=process.stderr.readline()
        assert b'Learning scheduler started' in line,line
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5)==0
    finally:
        if process.poll() is None: process.kill();process.wait()
        selector.close();process.stdout.close();process.stderr.close()


def test_catalog_command_and_failed_database_exit(tmp_path):
    envfile=tmp_path/'test.env'
    envfile.write_text(f'TUTOR_DATABASE_PATH={tmp_path / "db"}\n')
    argv,env=command(envfile,'catalog-put','--id',str(uuid4()),'--name','函数','--min-grade','10','--max-grade','12')
    result=subprocess.run(argv,env=env,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    envfile.write_text(f'TUTOR_DATABASE_PATH={tmp_path}\n')
    argv,env=command(envfile,'scheduler')
    result=subprocess.run(argv,env=env,capture_output=True,timeout=10)
    assert result.returncode==1 and b'Traceback' not in result.stderr
