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

# Closes the timestamps comment posted after the stream. No link: YouTube
# held or hid the bot's comments that carried one, so creators never got them.
COMMENT_FOOTER = (
    "Thank you for using Tsnip. It's free — if it helped, support it by "
    "playing Glide, my word puzzle game on the Play Store."
)

# YouTube limits
YOUTUBE_COMMENT_MAX_LENGTH = 9000
CHAT_MAX_LENGTH = 200
