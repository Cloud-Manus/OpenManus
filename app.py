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


async def run_task(task_id: str, prompt: str):
    try:
        task_manager.tasks[task_id].status = "running"

        agent = Manus(
            name="Manus",
            description="A versatile agent that can solve various tasks using multiple tools",
        )

        # Register event handlers for direct event flow instead of log parsing
        async def on_thinking(data):
            await task_manager.update_task_step(
                task_id, data["step"], data["content"], "think"
            )

        async def on_tool_select(data):
            tools_str = ", ".join([tool["name"] for tool in data["tools"]])
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"Selected tools: {tools_str}",
                "tool"
            )

        async def on_tool_execute(data):
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"Executing tool: {data['tool']}\nInput: {data['arguments']}",
                "tool"
            )

        async def on_tool_result(data):
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"Result from {data['tool']}: {data['result']}",
                "act"
            )

        async def on_state_change(data):
            if data["to"] == "FINISHED":
                await task_manager.update_task_step(
                    task_id, 0, "Task completed successfully", "complete"
                )

        async def on_error(data):
            await task_manager.update_task_step(
                task_id, 0, f"Error: {data['message']}", "error"
            )

        async def on_step_complete(data):
            await task_manager.update_task_step(
                task_id, data["step"], f"Step {data['step']}/{data['max_steps']} complete", "step"
            )

        async def on_task_complete(data):
            await task_manager.complete_task(task_id)

        async def on_browser_state(data):
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"Browser at: {data['url']} - {data['title']}",
                "browser"
            )

        async def on_manus_context(data):
            browser_status = "using browser" if data["browser_in_use"] else "not using browser"
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"Context update: {browser_status}, messages: {data['message_count']}",
                "context"
            )

        # 计划相关事件处理器
        async def on_plan_status(data):
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"Plan status updated - current step: {data['current_step_index'] if data['current_step_index'] is not None else 'N/A'}",
                "plan"
            )

        async def on_plan_step(data):
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"Plan step {data['step_index']} using {data['tool_name']}",
                "plan_step"
            )

        async def on_plan_step_completed(data):
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"Completed plan step {data['step_index']} with {data['tool_name']}",
                "plan_step"
            )

        # MCP相关事件处理器
        async def on_mcp_connected(data):
            await task_manager.update_task_step(
                task_id,
                0,
                f"Connected to MCP via {data['connection_type']} with {data['tools_count']} tools",
                "mcp"
            )

        async def on_mcp_disconnected(data):
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"MCP disconnected: {data['reason']}",
                "mcp"
            )

        async def on_mcp_tools_changed(data):
            added = ", ".join(data["tools_added"]) if data["tools_added"] else "none"
            removed = ", ".join(data["tools_removed"]) if data["tools_removed"] else "none"
            await task_manager.update_task_step(
                task_id,
                data["step"],
                f"MCP tools changed - Added: {added}, Removed: {removed}",
                "mcp"
            )

        # 流程相关事件处理器
        async def on_flow_start(data):
            await task_manager.update_task_step(
                task_id,
                0,
                f"Flow started with input: {data['input'][:50]}{'...' if len(data['input']) > 50 else ''}",
                "flow"
            )

        async def on_flow_step(data):
            agent_info = f" via agent {data['agent_key']}" if "agent_key" in data else ""
            step_info = f" - step {data['step']}" if "step" in data else ""
            await task_manager.update_task_step(
                task_id,
                0,
                f"Flow step executed{agent_info}{step_info}",
                "flow_step"
            )

        async def on_flow_agent_switch(data):
            await task_manager.update_task_step(
                task_id,
                0,
                f"Switching from agent {data['from_agent']} to {data['to_agent']} for step {data['step_index']}",
                "flow"
            )

        async def on_flow_complete(data):
            await task_manager.update_task_step(
                task_id,
                0,
                "Flow execution completed",
                "flow"
            )

        async def on_flow_error(data):
            await task_manager.update_task_step(
                task_id,
                0,
                f"Flow error: {data['error']} - {data['message']}",
                "error"
            )

        async def on_plan_create(data):
            status = data["status"]
            status_text = {
                "starting": "Creating plan...",
                "completed": "Plan created successfully",
                "completed_default": "Default plan created",
            }.get(status, status)

            await task_manager.update_task_step(
                task_id,
                0,
                f"Plan {data['plan_id']}: {status_text}",
                "plan"
            )

        async def on_plan_update(data):
            await task_manager.update_task_step(
                task_id,
                0,
                f"Plan step {data['step_index']} status changed to: {data['status']}",
                "plan"
            )

        # Register all event handlers
        agent.register_event_handler("thinking", on_thinking)
        agent.register_event_handler("tool_select", on_tool_select)
        agent.register_event_handler("tool_execute", on_tool_execute)
        agent.register_event_handler("tool_result", on_tool_result)
        agent.register_event_handler("state_change", on_state_change)
        agent.register_event_handler("error", on_error)
        agent.register_event_handler("step_complete", on_step_complete)
        agent.register_event_handler("task_complete", on_task_complete)
        agent.register_event_handler("browser_state", on_browser_state)
        agent.register_event_handler("manus_context", on_manus_context)
        agent.register_event_handler("plan_status", on_plan_status)
        agent.register_event_handler("plan_step", on_plan_step)
        agent.register_event_handler("plan_step_completed", on_plan_step_completed)
        agent.register_event_handler("mcp_connected", on_mcp_connected)
        agent.register_event_handler("mcp_disconnected", on_mcp_disconnected)
        agent.register_event_handler("mcp_tools_changed", on_mcp_tools_changed)

        # 注册流程事件处理器 (如果是使用flow的情况)
        if hasattr(agent, "register_flow_handlers"):
            agent.register_flow_handlers({
                "flow_start": on_flow_start,
                "flow_step": on_flow_step,
                "flow_agent_switch": on_flow_agent_switch,
                "flow_complete": on_flow_complete,
                "flow_error": on_flow_error,
                "plan_create": on_plan_create,
                "plan_update": on_plan_update,
                "plan_step_start": on_plan_step,
                "plan_step_complete": on_plan_step_completed,
            })

        # Keep a basic log handler for console output
        from app.logger import logger

        # We still keep the log handler for backward compatibility and debugging
        class SSELogHandler:
            def __init__(self, task_id):
                self.task_id = task_id

            async def __call__(self, message):
                import re

                # Extract - Subsequent Content
                cleaned_message = re.sub(r"^.*? - ", "", message)

                # Simple log entries (these are now secondary to the event system)
                await task_manager.update_task_step(
                    self.task_id, 0, cleaned_message, "log"
                )

        sse_handler = SSELogHandler(task_id)
        logger.add(sse_handler)

        result = await agent.run(prompt)
        await task_manager.update_task_step(task_id, 1, result, "result")
    except Exception as e:
        await task_manager.fail_task(task_id, str(e))


@app.get("/tasks/{task_id}/events")
async def task_events(task_id: str):
    async def event_generator():
        if task_id not in task_manager.queues:
            yield f"event: error\ndata: {dumps({'message': 'Task not found'})}\n\n"
            return

        queue = task_manager.queues[task_id]

        task = task_manager.tasks.get(task_id)
        if task:
            yield f"event: status\ndata: {dumps({'type': 'status', 'status': task.status, 'steps': task.steps})}\n\n"

        while True:
            try:
                event = await queue.get()
                formatted_event = dumps(event)

                yield ": heartbeat\n\n"

                if event["type"] == "complete":
                    yield f"event: complete\ndata: {formatted_event}\n\n"
                    break
                elif event["type"] == "error":
                    yield f"event: error\ndata: {formatted_event}\n\n"
                    break
                elif event["type"] == "step":
                    task = task_manager.tasks.get(task_id)
                    if task:
                        yield f"event: status\ndata: {dumps({'type': 'status', 'status': task.status, 'steps': task.steps})}\n\n"
                    yield f"event: {event['type']}\ndata: {formatted_event}\n\n"
                # 支持所有可能的事件类型
                elif event["type"] in [
                    "think", "tool", "act", "run", "browser", "context", "log",
                    "plan", "plan_step", "mcp", "flow", "flow_step"
                ]:
                    yield f"event: {event['type']}\ndata: {formatted_event}\n\n"
                else:
                    yield f"event: {event['type']}\ndata: {formatted_event}\n\n"

            except asyncio.CancelledError:
                print(f"Client disconnected for task {task_id}")
                break
            except Exception as e:
                print(f"Error in event stream: {str(e)}")
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
