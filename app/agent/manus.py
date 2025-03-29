from typing import Callable, Dict

from pydantic import Field

from app.agent.browser import BrowserAgent
from app.config import config
from app.flow.base import BaseFlow
from app.flow.flow_factory import FlowFactory, FlowType
from app.prompt.browser import NEXT_STEP_PROMPT as BROWSER_NEXT_STEP_PROMPT
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.tool import Terminate, ToolCollection
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.python_execute import PythonExecute
from app.tool.str_replace_editor import StrReplaceEditor


class Manus(BrowserAgent):
    """
    A versatile general-purpose agent that uses planning to solve various tasks.

    This agent extends BrowserAgent with a comprehensive set of tools and capabilities,
    including Python execution, web browsing, file operations, and information retrieval
    to handle a wide range of user requests.
    """

    name: str = "Manus"
    description: str = (
        "A versatile agent that can solve various tasks using multiple tools"
    )

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)
    next_step_prompt: str = NEXT_STEP_PROMPT

    max_observe: int = 10000
    max_steps: int = 20

    # Add general-purpose tools to the tool collection
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PythonExecute(), BrowserUseTool(), StrReplaceEditor(), Terminate()
        )
    )

    # 流处理相关属性
    active_flow: BaseFlow = None
    flow_event_handlers: Dict[str, Callable] = Field(default_factory=dict)

    async def think(self) -> bool:
        """Process current state and decide next actions with appropriate context."""
        # Store original prompt
        original_prompt = self.next_step_prompt

        # Only check recent messages (last 3) for browser activity
        recent_messages = self.memory.messages[-3:] if self.memory.messages else []
        browser_in_use = any(
            "browser_use" in msg.content.lower()
            for msg in recent_messages
            if hasattr(msg, "content") and isinstance(msg.content, str)
        )

        # Emit manus context event
        await self.emit_event("manus_context", {
            "browser_in_use": browser_in_use,
            "step": self.current_step,
            "message_count": len(self.memory.messages)
        })

        if browser_in_use:
            # Override with browser-specific prompt temporarily to get browser context
            self.next_step_prompt = BROWSER_NEXT_STEP_PROMPT

        # Call parent's think method
        result = await super().think()

        # Restore original prompt
        self.next_step_prompt = original_prompt

        return result

    def register_flow_handlers(self, handlers: Dict[str, Callable]) -> None:
        """注册流程事件处理器

        Args:
            handlers: 事件类型到处理函数的映射
        """
        self.flow_event_handlers = handlers

    async def _create_flow(self, flow_type: FlowType, prompt: str) -> BaseFlow:
        """创建一个新的流程

        Args:
            flow_type: 流程类型
            prompt: 用户输入

        Returns:
            创建的流程实例
        """
        # 创建流程实例
        flow = FlowFactory.create_flow(flow_type, {"manus": self})

        # 注册事件处理器
        for event_type, handler in self.flow_event_handlers.items():
            flow.register_event_handler(event_type, handler)

        # 将代理事件映射到流程事件
        flow.register_agent_events("manus")

        # 保存当前流程
        self.active_flow = flow

        return flow

    async def use_planning_flow(self, prompt: str) -> str:
        """使用计划流程执行任务

        Args:
            prompt: 用户输入

        Returns:
            执行结果
        """
        # 创建计划流程
        flow = await self._create_flow(FlowType.PLANNING, prompt)

        # 执行流程
        result = await flow.execute(prompt)

        return result
