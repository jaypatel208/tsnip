DEFAULT_TEMPLATE = (
    "Timestamped (with a -{delay}s delay) by {user}{title_part}. "
    "All timestamps get commented after the stream ends. Tool used: {tool_used}"
)

CHANNEL_TEMPLATES = {
    "UCtYcMgBNKW1ptgBI4bimJXg": (
        "Clipped by {user} (with a -{delay}s delay){title_part}. Tool used: {tool_used}. "
        "Timestamps will be added in the comments after the stream ends ❤🎬"
    ),
    "UCRj_BU95SebaRi2FziXEoTg": (
        "Timestamp '{title_part}' with a delay of 42 seconds was captured by {user} using Tsnip."
    ),
}


def get_comment_template(channel_id):
    return CHANNEL_TEMPLATES.get(channel_id, DEFAULT_TEMPLATE)


def template_exists(channel_id):
    return channel_id in CHANNEL_TEMPLATES
