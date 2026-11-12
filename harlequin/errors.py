class HarlequinError(Exception):
    """Base error for well-formedness problems the decoder reports to callers."""


class FormatError(HarlequinError):
    pass


class UnsupportedError(HarlequinError):
    pass
