class ObjectDeleteFailedException(Exception):
    """Raised when the lambda fails to delete a file(s)"""

    pass


class InvalidS3PutEventException(Exception):
    """Raised when the object added to the bucket according to the provided event does not match the expected pattern"""

    pass


class UnprocessedKeysException(RuntimeError):
    """Raised when keys are unprocessed, either because the batch limit is exceeded, the size of the response is too big
    (>16Mb) or the keys were throttled because of ProvisionedReads too low on ddb"""

    pass
