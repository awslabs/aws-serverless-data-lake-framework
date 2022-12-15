import logging


def init_logger(file_name, log_level=None):
    if not log_level:
        log_level = "INFO"
    logging.basicConfig()
    logger = logging.getLogger(file_name)
    logger.setLevel(getattr(logging, log_level))
    return logger
