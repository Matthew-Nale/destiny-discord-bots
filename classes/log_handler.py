import logging
import os

def create_logger(name: str, main_logger: logging.Logger) -> logging.Logger:
    """Creates a unique logger for a newly initialized bot

    Args:
        name (str): Name of the bot. Used to name the new log file
        main_logger (logging.Logger): The logging.Logger to forward information onto.

    Returns:
        logging.Logger: Newly created logging.Logger for the specified bot.
    """
    
    if not os.path.exists('..\logs'):
        os.makedirs('..\logs')
    
    log_file = os.path.join('..\logs', f'{name}.log')
    
    new_logger = logging.getLogger(name)
    new_logger.setLevel(logging.DEBUG)
    
    handler = logging.FileHandler(log_file, mode="w")
    handler.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter('[{asctime}] {levelname:<8s} | {filename}:{funcName} | {message}', style='{')
    handler.setFormatter(formatter)
    
    new_logger.addHandler(handler)
    new_logger.addHandler(main_logger)
    
    return new_logger
    
def test_func(log: logging.Logger) -> None:
    """Tests the newly created logger to make sure the environment is setup correctly.

    Args:
        log (logging.Logger): The logging.Logger to test.
    """
    log.error("Testing Error")
    log.info("Testing Info")
    log.debug("Testing Debug")
    log.critical("Testing Critical")
    log.warning("Testing Warning")


if __name__ == "__main__":
    main_handler = logging.FileHandler('main.log', mode="w")
    main_handler.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter('[{asctime}] {levelname:<8s} | {name}:{funcName} | {message}', style='{')
    main_handler.setFormatter(formatter)
    
    main_logger = logging.getLogger('main_logger')
    main_logger.setLevel(logging.DEBUG)
    main_logger.addHandler(main_handler)
    
    log = create_logger('test', main_logger)
    test_func(log)
    log = create_logger('test2', main_logger)
    test_func(log)