class ConflictError(ValueError):
    """A request conflicts with the current conversation state."""


class InvalidRequestError(ValueError):
    """A request is syntactically valid but not allowed for this conversation."""
