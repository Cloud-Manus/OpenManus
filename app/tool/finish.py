import logging
from typing import Any, Optional

from app.tool.base import BaseTool, ToolResult
from app.tool.planning import PlanningTool

logger = logging.getLogger(__name__)


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
            "force": {
                "type": "boolean",
                "description": "Force finishing the task even if not all steps are complete. Default is false.",
            },
        },
        "required": ["result"],
    }

    # Initialize task completion flag and last result
    task_complete: bool = False
    last_result: Optional[str] = None
    planning_tool: Optional[PlanningTool] = None

    def __init__(self, planning_tool: Optional[PlanningTool] = None):
        """Initialize the finish tool with an optional reference to the planning tool."""
        super().__init__()
        self.planning_tool = planning_tool

    def set_planning_tool(self, planning_tool: PlanningTool):
        """Set the reference to the planning tool."""
        self.planning_tool = planning_tool

    async def execute(self, result: str = "", force: bool = False) -> ToolResult:
        """
        End the current task and provide a final result.

        Args:
            result: The final result or summary of the task. This will be returned to the user as the task's final output.
            force: Force finishing even if steps remain incomplete.

        Returns:
            ToolResult: Tool result object containing the completion status and result.
        """
        if not result:
            result = "Task completed."

        # Check if all steps in the active plan are completed
        if self.planning_tool and self.planning_tool._current_plan_id:
            plan_id = self.planning_tool._current_plan_id
            if plan_id in self.planning_tool.plans:
                plan = self.planning_tool.plans[plan_id]
                step_statuses = plan.get("step_statuses", [])
                steps = plan.get("steps", [])

                # Count incomplete steps
                incomplete_steps = sum(
                    1 for status in step_statuses if status != "completed"
                )

                if incomplete_steps > 0 and not force:
                    # Don't actually finish if steps remain and force=False
                    logger.warning(
                        f"Finish tool called with {incomplete_steps} incomplete steps"
                    )

                    warning_message = (
                        f"⚠️ Task completion attempted with {incomplete_steps} incomplete steps out of {len(steps)} total.\n\n"
                        f"To properly complete this task, you should continue with the remaining steps in the plan.\n\n"
                        f"Current plan status:\n"
                    )

                    # Add step status information
                    for i, (step, status) in enumerate(zip(steps, step_statuses)):
                        status_mark = "✓" if status == "completed" else "❌"
                        warning_message += f"{i}. {status_mark} {step}\n"

                    warning_message += (
                        f"\nPlease continue with the next incomplete step. "
                        f"If you believe the task is truly complete despite incomplete steps, "
                        f"you can use the 'finish' tool with force=true parameter."
                    )

                    # Don't set task_complete flag
                    return ToolResult(
                        output=warning_message,
                        error="Task has incomplete steps, not finishing yet.",
                    )

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
