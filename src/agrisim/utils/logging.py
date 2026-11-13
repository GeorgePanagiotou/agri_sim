"""Consistent logging for command-line pipelines."""
import logging

def get_logger(name='agrisim', level=logging.INFO):
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(levelname)s %(name)s: %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger
