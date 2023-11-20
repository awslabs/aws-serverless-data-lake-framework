import logging
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.type_defs import (
        AttributeValueTypeDef,
    )


def init_logger(file_name, log_level=None):
    if not log_level:
        log_level = "INFO"
    logging.basicConfig()
    logger = logging.getLogger(file_name)
    logger.setLevel(getattr(logging, log_level))
    return logger


def serialize_dynamodb_item(
    item: Mapping[str, Any], serializer: Optional[TypeSerializer] = None
) -> Dict[str, "AttributeValueTypeDef"]:
    serializer = serializer if serializer else TypeSerializer()
    return {k: serializer.serialize(v) for k, v in item.items()}


def deserialize_dynamodb_item(
    item: Mapping[str, "AttributeValueTypeDef"], deserializer: Optional[TypeDeserializer] = None
) -> Dict[str, Any]:
    deserializer = deserializer if deserializer else TypeDeserializer()
    return {k: deserializer.deserialize(v) for k, v in item.items()}
