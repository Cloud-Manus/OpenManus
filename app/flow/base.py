from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from app.agent.base import BaseAgent
from app.logger import logger


class BaseFlow(BaseModel, ABC):
    """Base class for execution flows supporting multiple agents"""

    agents: Dict[str, BaseAgent]
    tools: Optional[List] = None
    primary_agent_key: Optional[str] = None

    # 事件系统
    event_callbacks: Dict[str, List[Callable]] = Field(
        default_factory=lambda: {
            # 流程基础事件
            "flow_start": [],
            "flow_step": [],
            "flow_agent_switch": [],
            "flow_complete": [],
            "flow_error": [],

            # 计划相关事件
            "plan_create": [],
            "plan_update": [],
            "plan_step_start": [],
            "plan_step_complete": [],
        },
        description="事件回调注册表",
        exclude=True,
    )

    class Config:
        arbitrary_types_allowed = True

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        # Handle different ways of providing agents
        if isinstance(agents, BaseAgent):
            agents_dict = {"default": agents}
        elif isinstance(agents, list):
            agents_dict = {f"agent_{i}": agent for i, agent in enumerate(agents)}
        else:
            agents_dict = agents

        # If primary agent not specified, use first agent
        primary_key = data.get("primary_agent_key")
        if not primary_key and agents_dict:
            primary_key = next(iter(agents_dict))
            data["primary_agent_key"] = primary_key

        # Set the agents dictionary
        data["agents"] = agents_dict

        # Initialize using BaseModel's init
        super().__init__(**data)

    def register_event_handler(self, event_type: str, callback: Callable) -> None:
        """注册事件处理函数

        Args:
            event_type: 事件类型 (flow_start, flow_step, flow_agent_switch,
                        flow_complete, flow_error, plan_create, plan_update 等)
            callback: 当事件发生时要调用的异步函数
        """
        if event_type not in self.event_callbacks:
            self.event_callbacks[event_type] = []
        self.event_callbacks[event_type].append(callback)

    async def emit_event(self, event_type: str, data: Any) -> None:
        """发送事件到所有注册的处理器和事件总线

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        # 1. 发送到注册的处理器（保持现有逻辑以保证兼容）
        if event_type in self.event_callbacks:
            for callback in self.event_callbacks[event_type]:
                try:
                    await callback(data)
                except Exception as e:
                    logger.error(f"事件处理器错误 {event_type}: {str(e)}")

        # 2. 发送到事件总线（直接透传给前端）
        if hasattr(self, 'task_id') and self.task_id:
            # 添加来源信息
            enhanced_data = {
                "source": "flow",
                "flow_type": self.__class__.__name__,
                "event_type": event_type,
                **data
            } if isinstance(data, dict) else {
                "source": "flow",
                "flow_type": self.__class__.__name__,
                "event_type": event_type,
                "data": data
            }

            from app.event_bus import event_bus
            await event_bus.emit(self.task_id, event_type, enhanced_data)

    def register_agent_events(self, agent_key: str, flow_event_map: Dict[str, str] = None) -> None:
        """将代理事件映射到流程事件

        Args:
            agent_key: 要注册事件的代理键
            flow_event_map: 代理事件到流程事件的映射，默认为None
        """
        agent = self.agents.get(agent_key)
        if not agent:
            logger.warning(f"无法找到代理: {agent_key}")
            return

        # 默认映射
        if flow_event_map is None:
            flow_event_map = {
                "thinking": "flow_step",
                "tool_select": "flow_step",
                "tool_execute": "flow_step",
                "tool_result": "flow_step",
                "error": "flow_error",
                "task_complete": "flow_complete"
            }

        # 注册事件处理器
        for agent_event, flow_event in flow_event_map.items():
            agent.register_event_handler(
                agent_event,
                lambda data, agent_key=agent_key, flow_event=flow_event:
                    self._on_agent_event(agent_key, flow_event, data)
            )

    async def _on_agent_event(self, agent_key: str, flow_event: str, data: Any) -> None:
        """代理事件处理函数

        Args:
            agent_key: 发出事件的代理键
            flow_event: 要转换成的流程事件类型
            data: 事件数据
        """
        # 添加代理信息
        enhanced_data = {"agent_key": agent_key, **data} if isinstance(data, dict) else data
        # 转发到流程事件
        await self.emit_event(flow_event, enhanced_data)

    @property
    def primary_agent(self) -> Optional[BaseAgent]:
        """Get the primary agent for the flow"""
        return self.agents.get(self.primary_agent_key)

    def get_agent(self, key: str) -> Optional[BaseAgent]:
        """Get a specific agent by key"""
        return self.agents.get(key)

    def add_agent(self, key: str, agent: BaseAgent) -> None:
        """Add a new agent to the flow"""
        self.agents[key] = agent

    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """Execute the flow with given input"""
        # 在子类实现中应当发出 flow_start 和 flow_complete 事件
        await self.emit_event("flow_start", {"input": input_text})
        # 执行流程...
        # 完成时应当发出 flow_complete 事件
        # await self.emit_event("flow_complete", {"result": result})
