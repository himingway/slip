from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    # Keywords
    MODULE = auto()
    PARAM = auto()
    LOCALPARAM = auto()
    LOGIC = auto()
    SIGNED = auto()
    ASSIGN = auto()
    SEQ = auto()
    COMB = auto()
    INITIAL = auto()
    POS = auto()
    NEG = auto()
    IF = auto()
    ELSE = auto()
    FOR = auto()
    CASE = auto()
    CASEZ = auto()
    CASEX = auto()
    DEFAULT = auto()
    INSIDE = auto()
    TICK_FOR = auto()
    TICK_IF = auto()
    TICK_ELSE = auto()
    TICK_IDENT = auto()
    DEFUN = auto()
    RETURN = auto()
    INCLUDE = auto()

    # Literals
    IDENT = auto()
    INT_LITERAL = auto()
    STRING_LITERAL = auto()

    # Operators
    EQ = auto()        # =
    LE = auto()        # <=
    PLUS = auto()      # +
    MINUS = auto()     # -
    STAR = auto()      # *
    SLASH = auto()     # /
    PERCENT = auto()   # %
    EQ_EQ = auto()     # ==
    BANG_EQ = auto()   # !=
    LT = auto()        # <
    GT = auto()        # >
    GT_EQ = auto()     # >=
    AMP_AMP = auto()   # &&
    PIPE_PIPE = auto() # ||
    BANG = auto()      # !
    TILDE = auto()     # ~
    AMP = auto()       # &
    PIPE = auto()      # |
    CARET = auto()     # ^
    LT_LT = auto()        # <<
    GT_GT = auto()        # >>
    LT_LT_LT = auto()    # <<<
    GT_GT_GT = auto()    # >>>
    STAR_STAR = auto()   # **
    EQ_EQ_EQ = auto()    # ===
    BANG_EQ_EQ = auto()  # !==
    QUESTION = auto()     # ?
    TICK = auto()      # '
    BACKTICK = auto()  # `
    TICK_ZERO = auto() # '0
    TICK_ONE = auto()  # '1
    ARROW = auto()     # =>
    AT = auto()        # @

    # Compound assignment operators
    PLUS_EQ = auto()       # +=
    MINUS_EQ = auto()      # -=
    STAR_EQ = auto()       # *=
    SLASH_EQ = auto()      # /=
    PERCENT_EQ = auto()    # %=
    AMP_EQ = auto()        # &=
    PIPE_EQ = auto()       # |=
    CARET_EQ = auto()      # ^=
    LT_LT_EQ = auto()     # <<=
    GT_GT_EQ = auto()      # >>=
    LT_LT_LT_EQ = auto()  # <<<=
    GT_GT_GT_EQ = auto()   # >>>=

    # Delimiters
    LBRACE = auto()    # {
    RBRACE = auto()    # }
    LBRACK = auto()    # [
    RBRACK = auto()    # ]
    LPAREN = auto()    # (
    RPAREN = auto()    # )

    # Punctuation
    SEMICOLON = auto()  # ;
    COLON = auto()      # :
    COMMA = auto()      # ,
    DOT = auto()        # .
    HASH = auto()       # #

    # End
    EOF = auto()


@dataclass(frozen=True)
class Token:
    type: TokenType
    value: str
    line: int
    col: int
