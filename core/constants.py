"""Shared constants — single source of truth for values used across layers."""

# Glide, the Tsnip dev's word puzzle game. Tsnip is free; its messages ask
# people to support it by playing Glide. /glide* are redirects in vercel.json
# that tag each placement for Play Console (utm_campaign tsnip_<placement>).
GLIDE_LINK = "https://tsnip.vercel.app/glide"

# Default comment template used when a channel has no custom one.
DEFAULT_COMMENT_TEMPLATE = (
    "Timestamped (-{delay}s) by {user}{title_part}. "
    "All timestamps get commented after the stream. "
    "Tsnip is free 💙 support it, play Glide: " + GLIDE_LINK
)

# Closes the timestamps comment posted after the stream. Linked comments do
# show publicly (lrCR0IV2cuU), and removing the link didn't stop YouTube
# holding some, so the link stays.
COMMENT_FOOTER = (
    "Thank you for using Tsnip. It's free — if it helped, support it by "
    f"playing Glide, my word puzzle game: {GLIDE_LINK}/comment"
)

# YouTube limits
YOUTUBE_COMMENT_MAX_LENGTH = 9000
CHAT_MAX_LENGTH = 200

# Bounds on a !ts, matching the checks on the timestamps table.
MESSAGE_MAX_LENGTH = 200
USER_MAX_LENGTH = 100
MAX_DELAY = 300
