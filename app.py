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

    async def complete_task(self, task_id: str):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = "completed"
            await self.queues[task_id].put(
                {"type": "status", "status": task.status, "steps": task.steps}
            )
            await self.queues[task_id].put({"type": "complete"})

    async def fail_task(self, task_id: str, error: str):
        if task_id in self.tasks:
            self.tasks[task_id].status = f"failed: {error}"
            await self.queues[task_id].put({"type": "error", "message": error})


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
from app.event_bus import event_bus


async def run_task(task_id: str, prompt: str):
    try:
        task_manager.tasks[task_id].status = "running"

        agent = Manus(
            name="Manus",
            description="A versatile agent that can solve various tasks using multiple tools",
        )

        # 设置task_id，使其能传递事件到总线
        agent.task_id = task_id

        # 保留基本日志处理器用于控制台输出
        from app.logger import logger

        # 简化的日志处理器，仅用于调试
        class SimplifiedLogHandler:
            async def __call__(self, message):
                # 仅打印到控制台，不再发送到前端
                print(f"Log: {message}")

        logger.add(SimplifiedLogHandler())

        # 执行代理任务
        result = await agent.run(prompt)

        # 更新任务状态为完成
        task_manager.tasks[task_id].status = "completed"

        # 发送最终结果事件
        await event_bus.emit(task_id, "task_result", {
            "result": result,
            "status": "completed"
        })

    except Exception as e:
        # 更新任务状态为失败
        if task_id in task_manager.tasks:
            task_manager.tasks[task_id].status = f"failed: {str(e)}"

        # 发送错误事件
        await event_bus.emit(task_id, "task_error", {
            "error": str(e)
        })


@app.get("/tasks/{task_id}/events")
async def task_events(task_id: str):
    async def event_generator():
        if task_id not in task_manager.tasks:
            yield f"event: error\ndata: {dumps({'message': 'Task not found'})}\n\n"
            return

        # 获取当前任务状态
        task = task_manager.tasks.get(task_id)
        if task:
            yield f"event: status\ndata: {dumps({'type': 'status', 'status': task.status})}\n\n"

        # 从事件总线注册队列
        from app.event_bus import event_bus
        queue = event_bus.register_task(task_id)

        try:
            while True:
                # 等待事件
                event = await queue.get()
                event_type = event["type"]
                data = event["data"]

                # 格式化事件数据
                formatted_data = dumps(data)

                # 发送事件
                yield f"event: {event_type}\ndata: {formatted_data}\n\n"

                # 心跳
                yield ": heartbeat\n\n"

                # 如果任务完成或失败，结束事件流
                if event_type in ["task_complete", "task_result", "task_error"] or \
                   task_manager.tasks[task_id].status in ["completed", "failed", "terminated"]:
                    yield f"event: complete\ndata: {dumps({'completed': True})}\n\n"
                    break

        except asyncio.CancelledError:
            print(f"Client disconnected for task {task_id}")
        except Exception as e:
            print(f"Error in event stream: {str(e)}")
            yield f"event: error\ndata: {dumps({'message': str(e)})}\n\n"
        finally:
            # 清理
            event_bus.unregister_queue(task_id, queue)

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
