import time

from flask import current_app, request
from flask_login import current_user

from .db import db


def log_audit(action, target=None, detail=None):
    """Best-effort audit log for financial actions. Never raises."""
    if not db:
        return
    try:
        db.audit_logs.insert_one({
            'user_id': current_user.id if current_user.is_authenticated else None,
            'username': current_user.username if current_user.is_authenticated else None,
            'action': action,
            'target': target,
            'detail': detail,
            'ip': request.remote_addr,
            'at': time.time(),
        })
    except Exception:
        current_app.logger.warning('audit log write failed', exc_info=True)
