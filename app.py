import argparse
import asyncio
import json
import os
import tomllib
import uuid
from datetime import datetime
from json import dumps
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


class Task(BaseModel):
    id: str
    prompt: str
    created_at: datetime
    status: str
    steps: list = []

    def model_dump(self, *args, **kwargs):
        data = super().model_dump(*args, **kwargs)
        data["created_at"] = self.created_at.isoformat()
        return data


class TaskManager:
    def __init__(self):
        self.tasks = {}
        self.queues = {}
        self.running_tasks = {}  # Store running task coroutines

    def create_task(self, prompt: str) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id, prompt=prompt, created_at=datetime.now(), status="pending"
        )
        self.tasks[task_id] = task
        self.queues[task_id] = asyncio.Queue()
        return task

    def store_running_task(self, task_id: str, task_coroutine):
        """Store the running task coroutine for possible cancellation later"""
        self.running_tasks[task_id] = task_coroutine

    async def terminate_task(self, task_id: str) -> bool:
        """Terminate a running task"""
        if task_id not in self.tasks:
            return False

        # Cancel the running task if it exists
        if task_id in self.running_tasks and not self.running_tasks[task_id].done():
            self.running_tasks[task_id].cancel()

            # Update task status
            self.tasks[task_id].status = "terminated"

            # Send termination event
            await self.queues[task_id].put(
                {
                    "type": "status",
                    "status": "terminated",
                    "steps": self.tasks[task_id].steps,
                }
            )
            await self.queues[task_id].put({"type": "complete", "terminated": True})

            return True
        return False

    async def update_task_step(
        self, task_id: str, step: int, result: str, step_type: str = "step"
    ):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.steps.append({"step": step, "result": result, "type": step_type})
            await self.queues[task_id].put(
                {"type": step_type, "step": step, "result": result}
            )
            await self.queues[task_id].put(
                {"type": "status", "status": task.status, "steps": task.steps}
            )

    async def complete_task(self, task_id: str, result: str):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = "completed"
            await self.queues[task_id].put(
                {"type": "status", "status": task.status, "steps": task.steps}
            )
            await self.queues[task_id].put({"type": "complete", "result": result})

    async def fail_task(self, task_id: str, error: str):
        if task_id in self.tasks:
            self.tasks[task_id].status = f"failed: {error}"
            await self.queues[task_id].put({"type": "error", "message": error})

    async def terminate_all_tasks(self):
        for task_id in self.running_tasks:
            await self.terminate_task(task_id)

    async def close_all_queues(self):
        for queue in self.queues.values():
            queue.close()

task_manager = TaskManager()


@app.get("/download")
async def download_file(file_path: str):
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path, filename=os.path.basename(file_path))


@app.post("/tasks")
async def create_task(prompt: str = Body(..., embed=True)):
    task = task_manager.create_task(prompt)
    task_coroutine = asyncio.create_task(run_task(task.id, prompt))
    task_manager.store_running_task(task.id, task_coroutine)
    return {"task_id": task.id}


from app.agent.manus import Manus


async def run_task(task_id: str, prompt: str):
    try:
        # update task status
        task_manager.tasks[task_id].status = "running"

        # create agent
        agent = Manus(
            name="Manus",
            description="A versatile agent that can solve various tasks using multiple tools",
        )

        # create event queue and connect to agent event manager
        queue = task_manager.queues[task_id]
        await agent.get_event_manager().connect_client(queue)
        # run agent
        result = await agent.run(prompt)
        # complete task
        await task_manager.complete_task(task_id, result)
    except Exception as e:
        print(f"task execution error: {str(e)}")
        await task_manager.fail_task(task_id, str(e))


@app.get("/tasks/{task_id}/events")
async def task_events(task_id: str):
    async def event_generator():
        if task_id not in task_manager.queues:
            yield f"event: error\ndata: {dumps({'message': 'Task not found'})}\n\n"
            return

        queue = task_manager.queues[task_id]

        # send initial task status
        task = task_manager.tasks.get(task_id)
        if task:
            yield f"event: status\ndata: {dumps({'type': 'status', 'status': task.status, 'steps': task.steps})}\n\n"

        while True:
            try:
                # get event
                event = await queue.get()

                # serialize event to json
                if isinstance(event, dict):
                    # if event is from task manager
                    event_type = event.get("type", "unknown")
                    formatted_event = dumps(event)
                else:
                    # if event is from event manager
                    event_type = (
                        event.type.value
                        if hasattr(event.type, "value")
                        else str(event.type)
                    )
                    formatted_event = event.model_dump_json()

                # send heartbeat
                yield ": heartbeat\n\n"

                # send event
                yield f"event: {event_type}\ndata: {formatted_event}\n\n"

                # check if event is complete
                if event_type == "complete" or event_type == "COMPLETE":
                    break

            except asyncio.CancelledError:
                print(f"client disconnected: {task_id}")
                break
            except Exception as e:
                print(f"event stream error: {str(e)}")
                yield f"event: error\ndata: {dumps({'message': str(e)})}\n\n"
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/tasks")
async def get_tasks():
    sorted_tasks = sorted(
        task_manager.tasks.values(), key=lambda task: task.created_at, reverse=True
    )
    return JSONResponse(
        content=[task.model_dump() for task in sorted_tasks],
        headers={"Content-Type": "application/json"},
    )


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in task_manager.tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_manager.tasks[task_id]


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500, content={"message": f"Server error: {str(exc)}"}
    )


def load_config():
    try:
        config_path = Path(__file__).parent / "config" / "config.toml"

        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        if "server" in config:
            return {"host": config["server"]["host"], "port": config["server"]["port"]}
        else:
            return {"host": "0.0.0.0", "port": 8000}
    except FileNotFoundError:
        raise RuntimeError(
            "Configuration file not found, please check if config/fig.toml exists"
        )
    except KeyError as e:
        raise RuntimeError(
            f"The configuration file is missing necessary fields: {str(e)}"
        )


@app.post("/tasks/{task_id}/terminate")
async def terminate_task(task_id: str):
    """Terminate a running task"""
    if task_id not in task_manager.tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    success = await task_manager.terminate_task(task_id)
    if success:
        return {"status": "terminated", "task_id": task_id}
    else:
        return {
            "status": "not_running",
            "task_id": task_id,
            "message": "Task is not currently running",
        }


if __name__ == "__main__":
    import uvicorn

    # create arg parser.
    parser = argparse.ArgumentParser(description="start openmanus server")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Server listening address (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server listening port (default: %(default)s)",
    )

    # parse command line arguments.
    args = parser.parse_args()

    # start the server.
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    async def shutdown():
        await task_manager.terminate_all_tasks()
        await task_manager.close_all_queues()
