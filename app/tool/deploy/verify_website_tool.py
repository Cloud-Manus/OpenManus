import asyncio
import re
from typing import Dict, List, Optional, Union

import aiohttp
from bs4 import BeautifulSoup

from app.logger import logger
from app.tool.base import BaseTool, ToolResult


class VerifyWebsiteTool(BaseTool):
    """Tool for verifying a deployed website meets expectations"""

    name: str = "verify_website"
    description: str = (
        "Verify that a deployed website is functioning correctly and meets expectations. "
        "This tool performs checks on the deployed site, including accessibility, content validation, "
        "and resource loading. Use after deploying a website to confirm it's ready for users."
        "when website is ready, return 'website is ready for users' and terminate the task."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL of the deployed website to verify",
            },
            "expected_content": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of text strings or HTML elements expected to be found in the page",
                "default": [],
            },
            "required_resources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of resource types or specific files that should be loaded (js, css, images)",
                "default": [],
            },
            "check_console_errors": {
                "type": "boolean",
                "description": "Whether to check for JavaScript console errors",
                "default": False,
            },
        },
        "required": ["url"],
    }

    async def execute(
        self,
        url: str,
        expected_content: List[str] = None,
        required_resources: List[str] = None,
        check_console_errors: bool = False,
    ) -> ToolResult:
        """
        Verify a deployed website meets expectations.

        Args:
            url: URL of the deployed website
            expected_content: List of content strings expected to be found
            required_resources: List of resources that should be loaded
            check_console_errors: Whether to check for JavaScript console errors

        Returns:
            ToolResult: Verification results and details
        """
        if expected_content is None:
            expected_content = []
        if required_resources is None:
            required_resources = []

        issues = []
        successes = []
        status_code = None
        page_content = None
        page_title = None
        resource_urls = []

        # Normalize URL
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        try:
            # Step 1: Basic accessibility check
            logger.info(f"Verifying website at: {url}")

            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(url, timeout=30) as response:
                        status_code = response.status
                        if status_code != 200:
                            issues.append(
                                f"Website returned status code {status_code} instead of 200"
                            )
                            return ToolResult(
                                output=f"Verification failed: Website not accessible (Status: {status_code})",
                                error=f"HTTP Status {status_code}",
                            )

                        # Get page content
                        page_content = await response.text()
                        successes.append(
                            f"Website is accessible (Status: {status_code})"
                        )

                        # Parse HTML
                        soup = BeautifulSoup(page_content, "html.parser")
                        page_title = soup.title.string if soup.title else "No title"

                        # Step 2: Check for expected content
                        content_issues = []
                        for content in expected_content:
                            if content.lower() in page_content.lower():
                                successes.append(f"Found expected content: '{content}'")
                            else:
                                content_issues.append(content)
                                issues.append(
                                    f"Expected content not found: '{content}'"
                                )

                        # Step 3: Check for required resources
                        # Collect resource URLs
                        for script in soup.find_all("script", src=True):
                            resource_urls.append(script["src"])
                        for link in soup.find_all("link", rel="stylesheet"):
                            if "href" in link.attrs:
                                resource_urls.append(link["href"])
                        for img in soup.find_all("img", src=True):
                            resource_urls.append(img["src"])

                        # Check required resources
                        resource_issues = []
                        for resource in required_resources:
                            found = False
                            for res_url in resource_urls:
                                if resource.lower() in res_url.lower():
                                    found = True
                                    successes.append(
                                        f"Found required resource matching: '{resource}'"
                                    )
                                    break
                            if not found:
                                resource_issues.append(resource)
                                issues.append(
                                    f"Required resource not found: '{resource}'"
                                )

                except aiohttp.ClientError as e:
                    issues.append(f"Connection error: {str(e)}")
                    return ToolResult(
                        output=f"Verification failed: Cannot connect to {url}. Error: {str(e)}",
                        error=f"Connection error: {str(e)}",
                    )
                except asyncio.TimeoutError:
                    issues.append("Connection timed out")
                    return ToolResult(
                        output=f"Verification failed: Timeout while connecting to {url}",
                        error="Connection timeout",
                    )

            # Prepare verification summary
            success_count = len(successes)
            issue_count = len(issues)

            # Determine overall verification status
            if issue_count == 0:
                verification_status = "Verification successful! ✅"
                success = True
            elif issue_count <= 2 and success_count > issue_count:
                verification_status = (
                    "Verification mostly successful, with minor issues. ⚠️"
                )
                success = True
            else:
                verification_status = "Verification failed with significant issues. ❌"
                success = False

            # Format output
            details = [
                f"Website: {url}",
                f"Title: {page_title}",
                f"Status: {status_code}",
                f"Resource count: {len(resource_urls)}",
                "",
            ]

            if successes:
                details.append("Successes:")
                for idx, success_item in enumerate(successes, 1):
                    details.append(f"  {idx}. {success_item}")
                details.append("")

            if issues:
                details.append("Issues:")
                for idx, issue in enumerate(issues, 1):
                    details.append(f"  {idx}. {issue}")
                details.append("")

            details.append(verification_status)

            output = "\n".join(details)

            # Return appropriate result
            return ToolResult(
                output=output,
                error=(
                    None
                    if success
                    else f"{issue_count} issues found during verification"
                ),
                url=url,
            )

        except Exception as e:
            error_message = str(e)
            logger.error(f"Error verifying website: {error_message}")
            return ToolResult(
                error=f"Error verifying website: {error_message}",
                output=f"Verification failed: {error_message}",
            )
