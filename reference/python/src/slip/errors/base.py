class SlipError(Exception):
    """Base class for all Slip compiler errors."""

    def __init__(self, file: str, line: int, col: int, message: str):
        self.file = file
        self.line = line
        self.col = col
        self.message = message
        super().__init__(self.format())

    def format(self) -> str:
        return f"Error at {self.file}:{self.line}:{self.col}: {self.message}"

    def __str__(self) -> str:
        return self.format()
