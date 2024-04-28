import json
import random
import asyncio
from typing import Iterable
from uuid import uuid4

import redis.asyncio as redis
import socketio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from celery.result import AsyncResult

from myapp.celery import app as celery_app


app = FastAPI()
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
combined_app = socketio.ASGIApp(sio, app)
redis_cli = redis.Redis(host='redis', port=6379, db=0, decode_responses=True)


async def get_users_task_ids(user_id: int) -> Iterable[str]:
    """
    We'll store the task IDs in a Redis set.
    """
    return await redis_cli.smembers(f"user:{user_id}:tasks")


async def get_users_tasks(user_id: int) -> Iterable[dict]:
    task_ids = await get_users_task_ids(user_id)
    return [
        async_result_to_dict(AsyncResult(task_id))
        for task_id in task_ids
    ]


async def add_user_task(user_id: int, task_id: str):
    """
    We'll store the task IDs in a Redis set.
    """
    await redis_cli.sadd(f"user:{user_id}:tasks", task_id)


def async_result_to_dict(async_result: AsyncResult) -> dict:
    """
    the `AsyncResult` object is not serializable, so we need to convert it:
    """
    try:
        result = str(async_result.result)
    except Exception as e:
        result = str(e)
    return {
        "task_id": async_result.task_id,
        "status": async_result.status,
        "date_done": async_result.date_done.isoformat() if async_result.date_done else None,
        "result": result,
    }

async def clear_user_tasks(user_id: int):
    """
    remove all the tasks for the user.
    """
    await redis_cli.delete(f"user:{user_id}:tasks")


async def remove_user_task(user_id: int, task_id: str):
    """
    remove a specific task for the user.
    """
    await redis_cli.srem(f"user:{user_id}:tasks", task_id)


@app.post("/taskrun/tasks")
async def add_task() -> dict:
    """
    this is an example endpoint where clients may create long running tasks.
    normally we'd use the tokens / cookies to authenticate the authorize this request.
    here we'll pretend that the user is authenticated and his user ID is equal to `42`.
    """
    user_id: int = 42

    # random task and data:
    task_name = "myapp.tasks.add"
    task_args = ["40", "2", random.randint(1, 100)]

    # IMPORTANT:
    # we're using a custom task ID (with a prefix). this allows us to easily
    # subscribe to all the updates using a pattern matching subscription (task:*):
    async_result: AsyncResult = celery_app.send_task(
        task_name,
        args=task_args,
        task_id=f"task:{str(uuid4())}",
    )

    task_id = async_result.task_id
    await add_user_task(user_id, task_id)

    # let's tell the client that the task was created, over socketio:
    user_room = f"user:{user_id}"
    await sio.emit("task_created", async_result_to_dict(async_result), room=user_room)
    return {"task_id": task_id}


@app.delete("/taskrun/tasks/{task_id}")
async def remove_task(task_id: str) -> dict:
    """
    this is an example endpoint where clients may remove tasks.
    normally we'd use the tokens / cookies to authenticate the authorize this request.
    here we'll pretend that the user is authenticated and his user ID is equal to `42`.
    """
    user_id: int = 42
    await remove_user_task(user_id, task_id)
    room_name = f"user:{user_id}"
    await sio.emit("task_removed", {"task_id": task_id}, room=room_name)
    return {"task_id": None}


@app.delete("/taskrun/tasks")
async def clear_tasks() -> dict:
    """
    this is an example endpoint where clients may remove all the tasks.
    normally we'd use the tokens / cookies to authenticate the authorize this request.
    here we'll pretend that the user is authenticated and his user ID is equal to `42`.
    """
    user_id: int = 42
    await clear_user_tasks(user_id)
    room_name = f"user:{user_id}"
    await sio.emit("tasks_cleared", room=room_name)
    return {"task_id": None}


@sio.on("connect")
async def handle_connect(sid, environ):
    print(f"Client {sid} connected", flush=True)
    # In production, we'd use the token (from environ) to authenticate the user.
    # Here we pretend that the user is authenticated and his user ID is equal to `42`:
    user_id: int = 42

    # the user get's his own "socketio room" (ie a "channel"):
    room_name = f"user:{user_id}"
    await sio.enter_room(sid, room_name)
    task_ids: Iterable[str] = await get_users_task_ids(user_id)
    initial_data = [
        async_result_to_dict(AsyncResult(task_id))
        for task_id in task_ids
    ]
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
                task_id = message_data["task_id"]
                async_result = AsyncResult(task_id)
                user_id = 42
                # we're sending the task updates to the user's socketio "room":
                await sio.emit("task_update", async_result_to_dict(async_result), room=f"user:{user_id}")
            else:
                await asyncio.sleep(0.1)


@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_event_loop()
    loop.create_task(task_updates_subscription())


@app.get("/")
async def index():
    return HTMLResponse(open("/src/myapp/public_www/index.html", "r").read())

