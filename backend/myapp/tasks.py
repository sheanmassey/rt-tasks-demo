import os
import time

from .celery import app


@app.task
def add(*args):
    """
    Lets simulate a long running task and add numbers together.
    """
    time.sleep(10)
    args = map(int, args)
    return sum(args)
