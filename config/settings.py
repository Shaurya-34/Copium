"""
CloudCFO — Application Settings
---------------------------------
Loads configuration from environment variables / .env file.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SlackSettings(BaseSettings):
    """Slack integration configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    webhook_url: str = Field(
        ...,
        alias="SLACK_WEBHOOK_URL",
        description="Slack Incoming Webhook URL",
    )
    channel: str = Field(
        default="#cloud-costs",
        alias="SLACK_CHANNEL",
        description="Target Slack channel (informational only, webhook determines channel)",
    )
    bot_name: str = Field(
        default="CloudCFO",
        alias="SLACK_BOT_NAME",
        description="Bot display name",
    )
    bot_emoji: str = Field(
        default=":cloud:",
        alias="SLACK_BOT_EMOJI",
        description="Bot emoji icon",
    )
    timeout_seconds: int = Field(
        default=10,
        alias="SLACK_TIMEOUT_SECONDS",
        description="HTTP request timeout for Slack API calls",
    )
    max_retries: int = Field(
        default=3,
        alias="SLACK_MAX_RETRIES",
        description="Maximum retry attempts on transient failures",
    )


# Singleton — import this from other modules
slack_settings = SlackSettings()
