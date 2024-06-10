import os
import sys
import time
import random
import functools

from .celery import app

LOG_DIR = "/tmp/logs"

os.makedirs(LOG_DIR, exist_ok=True)


def log_theif(func):
    @functools.wraps(func)
    def _log_theif(self, *args):
        log_path = os.path.join(LOG_DIR, f"{self.request.id}.log")
        _stdout = sys.stdout
        _stderr = sys.stderr
        with open(log_path, "a") as f:
            sys.stdout = f
            sys.stderr = f
            task_result = func(self, *args)

        ## from this point forward, we have the logs of the specific task execution (with potential retries)
        ## inside of the log file $log_path (inside the worker container).
        ## we could do something here, like push them to the backend of HTTP:

        # import requests
        # requests.post("http://backend:5000/log", json={
        #     "task_id": self.request.id,
        #     "log_path": log_path,
        #     "logs": open(log_path).read(),
        # })

        sys.stdout = _stdout
        sys.stderr = _stderr
        return task_result
    return _log_theif




@app.task(bind=True)
@log_theif
def add(self, *args):
    """
    Lets simulate a long running task and add numbers together.
    Sometimes we'll raise an exception.
    """
    try:
        print(f"this is a log message for task {self.request.id}")
        time.sleep(2 + random.randint(0, 3))
        args = map(int, args)
        print(f"here are my args: {args}")
        # let's raise some errors
        if random.randint(0, 100) < 25:
            print(f"oh no! I'm going to raise an exception!")
            raise Exception("Random exception")
        print(f"all done!")
        return sum(args)
    except Exception as e:
        raise self.retry(exc=e, countdown=5, max_retries=1 )
