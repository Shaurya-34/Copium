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
    signing_secret: str = Field(
        default="",
        alias="SLACK_SIGNING_SECRET",
        description="Slack App Signing Secret for verifying incoming webhooks",
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


class AnomalySettings(BaseSettings):
    """Cost anomaly detection configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    aws_region: str = Field(
        default="us-east-1",
        alias="AWS_REGION",
        description="AWS region used for session defaults.",
    )
    baseline_days: int = Field(
        default=7,
        alias="ANOMALY_BASELINE_DAYS",
        description="How many historical days to average for expected spend.",
    )
    data_lag_days: int = Field(
        default=1,
        alias="ANOMALY_DATA_LAG_DAYS",
        description="How many days behind today to inspect for finalized billing data.",
    )
    minimum_daily_cost: float = Field(
        default=10.0,
        alias="ANOMALY_MINIMUM_DAILY_COST",
        description="Ignore services below this daily spend.",
    )
    minimum_cost_increase: float = Field(
        default=5.0,
        alias="ANOMALY_MINIMUM_COST_INCREASE",
        description="Minimum absolute daily dollar increase to trigger detection.",
    )
    spike_multiplier_threshold: float = Field(
        default=1.5,
        alias="ANOMALY_SPIKE_MULTIPLIER",
        description="Required multiple over baseline to qualify as a spike.",
    )
    score_scale_dollars: float = Field(
        default=100.0,
        alias="ANOMALY_SCORE_SCALE_DOLLARS",
        description="Dollar scale used while computing anomaly scores.",
    )


anomaly_settings = AnomalySettings()
