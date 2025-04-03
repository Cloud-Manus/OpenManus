import os
import uuid
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import ConfigDict
from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos.cos_exception import CosClientError, CosServiceError

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


class COSUploadTool(BaseTool):
    """Tool for uploading files or content to cloud storage"""

    name: str = "cos_upload"
    description: str = (
        "Upload files or text content to cloud storage and get a public access URL. "
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
                "description": "Target directory path in COS (without leading/trailing slashes). Important for multi-file applications to maintain structure. Example: 'games/tetris' for a Tetris game.",
                "default": "",
            },
        },
        "required": [],
    }

    # Pydantic model config
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # COS credentials and settings
    default_secret_id: Optional[str] = None
    default_secret_key: Optional[str] = None
    default_region: Optional[str] = None
    default_bucket: Optional[str] = None
    default_domain: Optional[str] = None

    def __init__(self):
        super().__init__()
        # Load all necessary parameters from config
        self._load_config()

    def _load_config(self):
        """Load all required parameters from the configuration file"""
        try:
            if hasattr(config, "cos"):
                cos_config = config.cos
                self.default_secret_id = getattr(cos_config, "secret_id", None)
                self.default_secret_key = getattr(cos_config, "secret_key", None)
                self.default_region = getattr(cos_config, "region", None)
                self.default_bucket = getattr(cos_config, "bucket", None)
                self.default_domain = getattr(cos_config, "domain", None)

                # Configuration integrity validation
                if not all(
                    [
                        self.default_secret_id,
                        self.default_secret_key,
                        self.default_region,
                        self.default_bucket,
                    ]
                ):
                    logger.warning(
                        "COS configuration incomplete, tool may not function properly"
                    )
                else:
                    logger.info("COS configuration loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load COS configuration: {str(e)}")

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
        Upload file or content to cloud storage and return a public access URL.

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
            directory: Target directory in COS (important for multi-file applications)

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
                self.default_secret_id,
                self.default_secret_key,
                self.default_region,
                self.default_bucket,
            ]
        ):
            return ToolResult(
                error="COS configuration incomplete",
                output="Upload failed: System COS configuration is incomplete, please contact administrator",
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

            # Initialize COS client
            cos_config = CosConfig(
                Region=self.default_region,
                SecretId=self.default_secret_id,
                SecretKey=self.default_secret_key,
            )
            client = CosS3Client(cos_config)

            # Upload the file
            if file_path:
                # Upload from file
                response = client.upload_file(
                    Bucket=self.default_bucket,
                    LocalFilePath=file_path,
                    Key=key,
                    EnableMD5=False,
                    ContentType=content_type,
                )
                logger.info(f"Uploaded file {file_path} to COS as {key}")
            else:
                # Upload from content
                response = client.put_object(
                    Bucket=self.default_bucket,
                    Body=content.encode("utf-8"),
                    Key=key,
                    ContentType=content_type,
                )
                logger.info(f"Uploaded content as {key} with type {content_type}")

            # Make the object public for access
            client.put_object_acl(
                Bucket=self.default_bucket, Key=key, ACL="public-read"
            )

            # Generate access URL
            if self.default_domain:
                url = f"https://{self.default_domain}/{key}"
            else:
                url = f"https://{self.default_bucket}.cos.{self.default_region}.myqcloud.com/{key}"

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
            )
        except CosServiceError as e:
            logger.error(f"COS service error: {str(e)}")
            return ToolResult(
                error=f"COS service error: {str(e)}",
                output=f"Upload failed: COS service error: {str(e)}",
            )
        except CosClientError as e:
            logger.error(f"COS client error: {str(e)}")
            return ToolResult(
                error=f"COS client error: {str(e)}",
                output=f"Upload failed: COS client error: {str(e)}",
            )
        except Exception as e:
            logger.error(f"Error uploading to COS: {str(e)}")
            return ToolResult(
                error=f"Error uploading to COS: {str(e)}",
                output=f"Upload failed: {str(e)}",
            )
