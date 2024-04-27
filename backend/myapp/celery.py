import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()


app = Celery(
    'tasks',
    broker=os.environ['CELERY_BROKER_URL'],
    backend=os.environ['CELERY_RESULT_BACKEND'],
    task_track_started=True,
)

# app.conf.result_backend = os.environ['CELERY_RESULT_BACKEND']
