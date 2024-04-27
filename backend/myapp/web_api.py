import os
import json
import asyncio
import dataclasses
from dataclasses import dataclass
from uuid import uuid4
import redis.asyncio as redis
import socketio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

from myapp.celery import app as celery_app

load_dotenv()


app = FastAPI()
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
combined_app = socketio.ASGIApp(sio, app)
redis_cli = redis.Redis(host='redis', port=6379, db=0)


CELERY_TASKS: list = []


@dataclass
class CeleryTask:
    id: str
    name: str
    args: list[str]
    status: str
    created_by: int # user_id


def get_tasks_by_user_id(user_id: int) -> list[dict]:
    return [
        dataclasses.asdict(task)
        for task in CELERY_TASKS
        if task.created_by == user_id
    ]


@app.post("/taskrun/tasks")
async def add_task() -> dict:
    """
    this is an example endpoint where clients may create long running tasks.
    normally we'd use the tokens / cookies to authenticate the authorize this request.
    here we'll pretent that the user is authenticated and his user ID is equal to `42`.
    """
    user_id: int = 42

    # random task and data:
    task_name = "myapp.tasks.add"
    task_args = ["40", "2"]

    # IMPORTANT:
    # we're using a custom task ID (with a prefix). this allows up to easily
    # subscribe to all the updates using a pattern matching subscription (task:*):

    task = celery_app.send_task(task_name, args=task_args, task_id=f"task:{str(uuid4())}")

    task_id = task.id
    celery_task = CeleryTask(
        id=task_id,
        name=task_name,
        args=task_args,
        status=task.status,
        created_by=user_id
    )

    # save my our "db":
    CELERY_TASKS.append(celery_task)

    # let's tell the client that the task was created, over socketio:
    user_room = f"user:{user_id}"
    await sio.emit("task_created", dataclasses.asdict(celery_task), room=user_room)

    return {"task_id": task_id}


@sio.on("connect")
async def handle_connect(sid, environ):
    print(f"Client {sid} connected", flush=True)

    # In production, we'd use the token (from environ) to authenticate the user.
    # Here we pretend that the user is authenticated and his user ID is equal to `42`:
    user_id: int = 42

    # the user get's his own "socketio room" (ie a "channel"):
    room_name = f"user:{user_id}"
    await sio.enter_room(sid, room_name)

    initial_data = get_tasks_by_user_id(user_id)
    # get the most recent data for the tasks:
    for task in initial_data:
        task_id = task["id"]
        task_obj = celery_app.AsyncResult(task_id)
        task["status"] = task_obj.status
        task["data"] = task_obj.result

    print("Sending initial data", flush=True)
    print(initial_data, flush=True)

    await sio.emit("initial_data", initial_data, room=room_name)


@sio.on("disconnect")
async def handle_disconnect(sid):
    print(f"Client {sid} disconnected", flush=True)


async def task_updates_subscription():
    """
    here we're subscribing to the task updates using the `task:*` pattern.
    these updates are published by the Celery `RedisBackend` backend.
    """
    async with redis_cli.pubsub() as pubsub:
        # NOTE: for some reason I can't explain.. the messages being published here by Celery
        # are prefixed with "celeery-task-meta-". To work around this, we're using 2 patterns:
        await pubsub.psubscribe("*-task:*")
        # await pubsub.psubscribe("*")
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5)
            if message:
                message_data = json.loads(message["data"])
                print(message_data, flush=True)
                task_id = message_data["task_id"]

                task = celery_app.AsyncResult(task_id)
                task_data = task.result
                task_status = task.status

                #
                user_id = 42

                # we're sending the task updates to the user's socketio "room":
                await sio.emit("task_update", {
                    "task_id": task_id,
                    "status": task_status,
                    "data": task_data
                }, room=f"user:{user_id}")
            else:
                await asyncio.sleep(0.1)


@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_event_loop()
    # loop.create_task(task_logger())
    loop.create_task(task_updates_subscription())


@app.get("/")
async def index():
    return HTMLResponse(open("/src/myapp/public_www/index.html", "r").read())
