import os
import time
import random

from .celery import app


@app.task(bind=True)
def add(self, *args):
    """
    Lets simulate a long running task and add numbers together.
    Sometimes we'll raise an exception.
    """
    try:
        time.sleep(2 + random.randint(0, 3))
        args = map(int, args)

        # let's raise some errors
        if random.randint(0, 100) < 25:
            raise Exception("Random exception")

        return sum(args)
    except Exception as e:
        raise self.retry(exc=e, countdown=5, max_retries=1 )
