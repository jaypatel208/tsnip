"""Domain exceptions — typed errors that cross layer boundaries cleanly."""


class TsnipError(Exception):
    """Base exception for all tsnip domain errors."""


class ValidationError(TsnipError):
    """Raised when input validation fails (e.g. bad chat_id format)."""


class ConfigurationError(TsnipError):
    """Raised when required configuration is missing or invalid."""


class ExternalServiceError(TsnipError):
    """Raised when an external service (Supabase, YouTube, Discord) fails."""
