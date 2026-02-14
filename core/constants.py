"""Shared constants — single source of truth for values used across layers."""

# Default comment template used when a channel has no custom one.
DEFAULT_COMMENT_TEMPLATE = (
    "Timestamped (with a -{delay}s delay) by {user}{title_part}."
    "All timestamps get commented after the stream ends. Tool used: {tool_used}"
)

# YouTube limits
YOUTUBE_COMMENT_MAX_LENGTH = 9000
