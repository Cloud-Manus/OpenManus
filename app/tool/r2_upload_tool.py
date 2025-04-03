import os
import uuid
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError
from pydantic import ConfigDict

from app.config import config
from app.logger import logger
from app.tool.base import BaseTool, ToolResult

# Common MIME types mapping for file extensions
MIME_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".xml": "application/xml",
}


class R2UploadTool(BaseTool):
    """Tool for uploading files or content to Cloudflare R2 storage"""

    name: str = "r2_upload"
    description: str = (
        "Upload files or text content to Cloudflare R2 storage and get a public access URL. "
        "Supports uploading complete web applications including HTML games with proper directory structure. "
        "When uploading multiple related files (like HTML, CSS, JS and images), maintain their original "
        "directory structure to preserve internal references. For web applications or games, upload all "
        "files to the same directory structure and access them via the main HTML file URL. "
        "Examples: Upload an HTML game with its assets; publish web content; share documents or images. "
        "All uploaded files are publicly accessible via the returned URL."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Local file path to upload. For HTML games or web apps, specify the main HTML file first.",
            },
            "content": {
                "type": "string",
                "description": "Text content to upload (HTML, text, etc.). Used when directly creating files without local source.",
            },
            "file_name": {
                "type": "string",
                "description": "Specify the file name for upload (auto-generated if not provided). For HTML files, 'index.html' is recommended.",
                "default": "",
            },
            "directory": {
                "type": "string",
                "description": "Target directory path in R2 (without leading/trailing slashes). Important for multi-file applications to maintain structure. Example: 'games/tetris' for a Tetris game.",
                "default": "",
            },
        },
        "required": [],
    }

    # Pydantic model config
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # R2 credentials and settings
    default_account_id: Optional[str] = None
    default_access_key_id: Optional[str] = None
    default_secret_access_key: Optional[str] = None
    default_bucket: Optional[str] = None
    default_domain: Optional[str] = None

    def __init__(self):
        super().__init__()
        # Load all necessary parameters from config
        self._load_config()

    def _load_config(self):
        """Load all required parameters from the configuration file"""
        try:
            if hasattr(config, "r2") and config.r2 is not None:
                self.default_account_id = config.r2.account_id
                self.default_access_key_id = config.r2.access_key_id
                self.default_secret_access_key = config.r2.secret_access_key
                self.default_bucket = config.r2.bucket
                self.default_domain = config.r2.domain

                # Configuration integrity validation
                if not all(
                    [
                        self.default_account_id,
                        self.default_access_key_id,
                        self.default_secret_access_key,
                        self.default_bucket,
                    ]
                ):
                    logger.warning(
                        "R2 configuration incomplete, tool may not function properly"
                    )
                else:
                    logger.info("R2 configuration loaded successfully")
            else:
                logger.warning("R2 configuration not found in config")
        except Exception as e:
            logger.warning(f"Failed to load R2 configuration: {str(e)}")

    def _get_mime_type(self, file_name: str) -> str:
        """Get MIME type based on file extension."""
        ext = os.path.splitext(file_name)[1].lower()
        return MIME_TYPES.get(ext, "application/octet-stream")

    async def execute(
        self,
        file_path: str = "",
        content: str = "",
        file_name: str = "",
        directory: str = "",
    ) -> ToolResult:
        """
        Upload file or content to Cloudflare R2 storage and return a public access URL.

        For HTML games or web applications, follow these steps:
        1. First upload the main HTML file (usually index.html)
        2. Then upload all related CSS, JS and asset files to the same directory structure
        3. Access the game via the URL of the main HTML file

        The directory parameter is crucial for maintaining structure. For example:
        - Upload main.html to "games/puzzle/" directory
        - Upload style.css to "games/puzzle/css/" directory
        - Upload game.js to "games/puzzle/js/" directory

        This preserves all relative paths referenced in the HTML file.

        Args:
            file_path: Local file path to upload
            content: Text content to upload directly (alternative to file_path)
            file_name: Custom file name for the uploaded content
            directory: Target directory in R2 (important for multi-file applications)

        Returns:
            ToolResult: Contains the public access URL or error information
        """
        # Validate input
        if not file_path and not content:
            return ToolResult(
                error="Must provide either file_path or content parameter",
                output="Upload failed: Please provide a file path or content",
            )

        # Validate configuration completeness
        if not all(
            [
                self.default_account_id,
                self.default_access_key_id,
                self.default_secret_access_key,
                self.default_bucket,
            ]
        ):
            return ToolResult(
                error="R2 configuration incomplete",
                output="Upload failed: System R2 configuration is incomplete, please contact administrator",
            )

        try:
            # Determine file name
            if not file_name:
                if file_path:
                    file_name = os.path.basename(file_path)
                else:
                    # Generate a random name for content uploads
                    file_name = f"upload_{uuid.uuid4().hex[:8]}"

                    # Add appropriate extension based on content
                    if (
                        "<html" in content.lower()
                        or "<!doctype html" in content.lower()
                    ):
                        file_name += ".html"
                    else:
                        file_name += ".txt"

            # Determine content type
            content_type = self._get_mime_type(file_name)

            # Create key (path in the bucket)
            key = file_name
            if directory:
                # Ensure directory doesn't have leading/trailing slashes
                directory = directory.strip("/")
                key = f"{directory}/{file_name}"

            # Initialize R2 client (using S3 compatible API)
            s3_client = boto3.client(
                "s3",
                endpoint_url=f"https://{self.default_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=self.default_access_key_id,
                aws_secret_access_key=self.default_secret_access_key,
                region_name="auto",  # R2 uses 'auto' as the region
            )

            # Upload the file
            if file_path:
                # Upload from file
                with open(file_path, "rb") as file_data:
                    s3_client.upload_fileobj(
                        file_data,
                        self.default_bucket,
                        key,
                        ExtraArgs={"ContentType": content_type, "ACL": "public-read"},
                    )
                logger.info(f"Uploaded file {file_path} to R2 as {key}")
            else:
                # Upload from content
                s3_client.put_object(
                    Bucket=self.default_bucket,
                    Key=key,
                    Body=content.encode("utf-8"),
                    ContentType=content_type,
                    ACL="public-read",
                )
                logger.info(f"Uploaded content as {key} with type {content_type}")

            # Generate access URL
            if self.default_domain:
                url = f"https://{self.default_domain}/{key}"
            else:
                # Default R2 public URL format
                url = f"https://{self.default_bucket}.{self.default_account_id}.r2.cloudflarestorage.com/{key}"

            # Add additional context for HTML files
            additional_info = ""
            if content_type in ["text/html", "text/htm"]:
                # If this is an index.html file, provide the directory URL too
                if file_name.lower() == "index.html" and directory:
                    directory_url = url.rsplit("/", 1)[0] + "/"
                    additional_info = f"\nYou can also access this HTML page using the directory URL: {directory_url}"
                else:
                    additional_info = "\nFor HTML content, you can directly access this URL in a browser."

                if directory:
                    additional_info += f"\nRemember to upload all related assets (CSS, JS, images) to the same directory structure '{directory}/'."

            return ToolResult(
                output=f"File uploaded successfully. Access URL: {url}{additional_info}",
                error=None,
                url=url,
            )
        except ClientError as e:
            error_message = str(e)
            logger.error(f"R2 client error: {error_message}")
            return ToolResult(
                error=f"R2 client error: {error_message}",
                output=f"Upload failed: R2 client error: {error_message}",
            )
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error uploading to R2: {error_message}")
            return ToolResult(
                error=f"Error uploading to R2: {error_message}",
                output=f"Upload failed: {error_message}",
            )
