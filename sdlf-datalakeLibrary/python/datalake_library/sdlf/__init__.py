import logging

from .__version__ import __title__, __version__  # noqa: F401;
from .client import SdlfClient  # noqa: F401;

name = "sdlf"

# Suppress boto3 logging
logging.getLogger("boto3").setLevel(logging.CRITICAL)
logging.getLogger("botocore").setLevel(logging.CRITICAL)
logging.getLogger("s3transfer").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
