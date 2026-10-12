from slip.errors.base import SlipError


class SlipSyntaxError(SlipError):
    """Error raised during lexing or parsing."""
