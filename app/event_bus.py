import asyncio
from typing import Any, Dict, List


class EventBus:
    """中央事件总线，收集所有模块emit的事件并转发到前端"""

    def __init__(self):
        self.task_event_queues: Dict[str, List[asyncio.Queue]] = {}

    def register_task(self, task_id: str) -> asyncio.Queue:
        """为任务注册事件队列"""
        if task_id not in self.task_event_queues:
            self.task_event_queues[task_id] = []

        queue = asyncio.Queue()
        self.task_event_queues[task_id].append(queue)
        return queue

    def unregister_queue(self, task_id: str, queue: asyncio.Queue) -> None:
        """注销队列"""
        if task_id in self.task_event_queues:
            if queue in self.task_event_queues[task_id]:
                self.task_event_queues[task_id].remove(queue)

    async def emit(self, task_id: str, event_type: str, data: Any) -> None:
        """发送事件到所有注册的队列"""
        if task_id not in self.task_event_queues:
            return

        event = {
            "type": event_type,
            "data": data
        }

        for queue in self.task_event_queues[task_id]:
            await queue.put(event)

# 全局单例
event_bus = EventBus()
