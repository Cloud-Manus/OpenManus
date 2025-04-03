from typing import Any, Optional

from app.tool.base import BaseTool, ToolResult


class FinishTool(BaseTool):
    """Tool that allows an agent to end the current task when the goal is achieved."""

    name: str = "finish"
    description: str = (
        "Ends the current task and provides a final result. Use this tool when the task objective has been completed "
        "and no further processing is needed. Provide a summary or final answer as the parameter. "
        "After calling this tool, the agent will stop execution and the task will be marked as complete."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "The final result, summary, or completion status of the task. Should include a direct answer to the user query or a summary of what was accomplished.",
            },
        },
        "required": ["result"],
    }

    # Initialize task completion flag and last result
    task_complete: bool = False
    last_result: Optional[str] = None

    async def execute(self, result: str = "") -> ToolResult:
        """
        End the current task and provide a final result.

        Args:
            result: The final result or summary of the task. This will be returned to the user as the task's final output.

        Returns:
            ToolResult: Tool result object containing the completion status and result.
        """
        if not result:
            result = "Task completed."

        # Set task completion flag and save result
        self.task_complete = True
        self.last_result = result

        return ToolResult(
            output=result,
            error=None,
        )

    def _set_task_complete(self):
        """
        Set internal flag indicating the task is complete.
        Agents should check this flag to determine whether to stop execution.
        """
        self.task_complete = True
