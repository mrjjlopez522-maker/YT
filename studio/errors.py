"""Exception hierarchy.

Every error carries a human-readable message that says what failed and, where
possible, what to do about it. `retryable` tells the retry helper whether a
second attempt can reasonably succeed.
"""


class StudioError(Exception):
    retryable = False

    def __init__(self, message, *, hint=None):
        super().__init__(message)
        self.hint = hint

    def __str__(self):
        base = super().__str__()
        return f"{base} (hint: {self.hint})" if self.hint else base


class ConfigError(StudioError):
    pass


class ValidationError(StudioError):
    pass


class RightsError(StudioError):
    """A source failed the rights gate. Never retried."""


class ProviderError(StudioError):
    """An external provider (API, TTS engine, LLM) failed."""

    def __init__(self, message, *, retryable=False, hint=None):
        super().__init__(message, hint=hint)
        self.retryable = retryable


class NetworkBlockedError(ProviderError):
    """The host is not reachable under the current network policy."""


class RateLimitedError(ProviderError):
    """The provider asked us to slow down for longer than we are willing to wait."""


class RenderError(StudioError):
    pass


class BudgetExceededError(StudioError):
    pass


class ApprovalRequiredError(StudioError):
    pass


class StateTransitionError(StudioError):
    pass


class DailyLimitError(StudioError):
    pass
