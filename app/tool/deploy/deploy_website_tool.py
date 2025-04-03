import os
from pathlib import Path
from typing import Optional
from pydantic import Field

from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.r2_upload_tool import R2UploadTool


class DeployWebsiteTool(BaseTool):
    """Tool for deploying static websites from a local folder to cloud storage"""

    name: str = "deploy_website"
    description: str = (
        "Deploy a static website from a local folder to cloud storage. "
        "This tool uploads all files in the specified directory while maintaining the directory structure. "
        "The folder MUST contain an index.html file as the main entry point. "
        "Returns the public URL to access the deployed website."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "folder_path": {
                "type": "string",
                "description": "Path to the local folder containing website files. Must include index.html file.",
            },
            "site_name": {
                "type": "string",
                "description": "Optional name for the website deployment. Will be used in the URL path.",
                "default": "",
            },
        },
        "required": ["folder_path"],
    }

    r2_upload_tool: R2UploadTool = Field(default_factory=R2UploadTool)

    def __init__(self):
        super().__init__()
        # Internal instance of R2UploadTool for file uploads
        self.r2_upload_tool = R2UploadTool()

    async def execute(
        self,
        folder_path: str,
        site_name: str = "",
    ) -> ToolResult:
        """
        Deploy a static website from a local folder to cloud storage.

        Args:
            folder_path: Path to the local folder containing website files
            site_name: Optional name for the website deployment

        Returns:
            ToolResult: Contains the public access URL to the website
        """
        # Validate input
        if not folder_path:
            return ToolResult(
                error="Folder path is required",
                output="Deployment failed: Please provide a valid folder path",
            )

        folder_path = Path(folder_path)
        if not folder_path.exists() or not folder_path.is_dir():
            return ToolResult(
                error=f"Directory not found: {folder_path}",
                output=f"Deployment failed: Directory {folder_path} not found or is not a directory",
            )

        # Verify index.html exists
        index_path = folder_path / "index.html"
        if not index_path.exists():
            return ToolResult(
                error="index.html not found in folder",
                output="Deployment failed: index.html file is required for website deployment",
            )

        # Generate site name if not provided
        if not site_name:
            import uuid

            site_name = f"site-{uuid.uuid4().hex[:8]}"

        # Directory in storage where website will be deployed
        site_path = f"websites/{site_name}"

        # Track uploaded files and any errors
        uploaded_files = []
        errors = []
        entry_url = None

        try:
            # First upload index.html as it's the entry point
            logger.info(f"Uploading index.html from {index_path}")
            result = await self.r2_upload_tool.execute(
                file_path=str(index_path),
                directory=site_path,
                file_name="index.html",
            )

            if result.error:
                return ToolResult(
                    error=f"Failed to upload index.html: {result.error}",
                    output=f"Deployment failed: {result.output}",
                )

            # Save the entry URL from the index.html upload
            entry_url = result.url
            uploaded_files.append("index.html")

            # Upload all other files in the directory, maintaining structure
            for file_path in folder_path.glob("**/*"):
                if file_path.is_file() and file_path != index_path:
                    # Calculate relative path for storage directory
                    rel_path = file_path.relative_to(folder_path)

                    # Create directory within site path
                    target_dir = str(Path(site_path) / rel_path.parent)
                    target_dir = target_dir.replace("\\", "/")  # Handle Windows paths

                    # Skip hidden files and directories
                    if any(part.startswith(".") for part in file_path.parts):
                        continue

                    logger.info(f"Uploading {rel_path} to {target_dir}")

                    # Upload the file
                    try:
                        file_result = await self.r2_upload_tool.execute(
                            file_path=str(file_path),
                            directory=target_dir,
                            file_name=file_path.name,
                        )

                        if file_result.error:
                            errors.append(
                                f"Failed to upload {rel_path}: {file_result.error}"
                            )
                        else:
                            uploaded_files.append(str(rel_path))
                    except Exception as e:
                        errors.append(f"Error uploading {rel_path}: {str(e)}")

            # Prepare result output
            if entry_url:
                output = f"Website deployed successfully. Access URL: {entry_url}\n"
                output += f"Files uploaded ({len(uploaded_files)}): {', '.join(uploaded_files[:5])}"
                if len(uploaded_files) > 5:
                    output += f" and {len(uploaded_files) - 5} more"

                if errors:
                    output += f"\nWarning: {len(errors)} files failed to upload."

                return ToolResult(
                    output=output,
                    error=None if not errors else "; ".join(errors[:3]),
                    url=entry_url,
                )
            else:
                return ToolResult(
                    error="Failed to deploy website: No entry URL obtained",
                    output="Deployment failed: Unable to upload index.html",
                )

        except Exception as e:
            error_message = str(e)
            logger.error(f"Error deploying website: {error_message}")
            return ToolResult(
                error=f"Error deploying website: {error_message}",
                output=f"Deployment failed: {error_message}",
            )
