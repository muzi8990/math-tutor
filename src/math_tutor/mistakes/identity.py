import ipaddress
from fastapi import HTTPException, Request
from .models import StudentContext


def get_student(request: Request) -> StudentContext:
    """Override this dependency with verified authentication for production."""
    config = request.app.state.mistake_settings
    host = request.client.host if request.client else ''
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == 'localhost'
    if config.enable_local_identity and config.local_student_id and loopback:
        return StudentContext(config.local_student_id, config.student_timezone)
    raise HTTPException(401, '请先登录；本地调试需显式启用测试身份。')
