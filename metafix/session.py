"""Serialize desktop session operations across HTTP and native callbacks."""
from functools import wraps
from threading import RLock

session_lock = RLock()


def exclusive(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not session_lock.acquire(blocking=False):
            return {"error": "Another operation is in progress"}, 409
        try:
            return function(*args, **kwargs)
        finally:
            session_lock.release()
    return wrapped
