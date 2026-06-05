"""Structured logging with timed rotating file handler for V12 PRO MAX."""
import os
import logging
from logging.handlers import TimedRotatingFileHandler
import datetime
from config import LOG_DIR, LOG_BACKUP_COUNT, IST

_loggers = {}  # cache to avoid duplicate handlers

def setup_logger(name="v12", level=logging.INFO):
    """Create or return a named logger with console + timed rotating file output."""
    if name in _loggers:
        return _loggers[name]
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    
    # Create log directory
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # File handler — timed rotation at midnight
    log_file = os.path.join(LOG_DIR, "v12.log")
    fh = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8"
    )
    fh.suffix = "%Y-%m-%d"
    fh.setLevel(logging.DEBUG)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    
    # Formatter
    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    _loggers[name] = logger
    return logger


def get_logger(module_name):
    """Get a child logger for a specific module."""
    parent = setup_logger()
    return parent.getChild(module_name)
