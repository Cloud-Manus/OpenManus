from typing import Optional

from pydantic import Field

from app.agent.base import BaseAgent
from app.llm import LLM
from app.logger import logger
from app.prompt.cot import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import AgentState, Message


class CoTAgent(BaseAgent):
    """Chain of Thought Agent - Focuses on demonstrating the thinking process of large language models without executing tools"""

    name: str = "cot"
    description: str = "An agent that uses Chain of Thought reasoning"

    system_prompt: str = SYSTEM_PROMPT
    next_step_prompt: Optional[str] = NEXT_STEP_PROMPT

    llm: LLM = Field(default_factory=LLM)

    max_steps: int = 1  # CoT typically only needs one step to complete reasoning

    async def step(self) -> str:
        """Execute one step of chain of thought reasoning"""
        logger.info(f"🧠 {self.name} is thinking...")

        await self.emit_event("step_start", {"step": self.current_step, "max_steps": self.max_steps})

        # If next_step_prompt exists and this isn't the first message, add it to user messages
        if self.next_step_prompt and len(self.messages) > 1:
            self.memory.add_message(Message.user_message(self.next_step_prompt))

        # Use system prompt and user messages
        response = await self.llm.ask(
            messages=self.messages,
            system_msgs=[Message.system_message(self.system_prompt)]
            if self.system_prompt
            else None,
        )

        # Emit thinking event
        await self.emit_event("thinking", {
            "content": response,
            "step": self.current_step
        })

        # Record assistant's response
        self.memory.add_message(Message.assistant_message(response))

        # Set state to finished after completion
        self.state = AgentState.FINISHED

        # Emit completion event
        await self.emit_event("task_complete", {"results": [response]})

        return response
