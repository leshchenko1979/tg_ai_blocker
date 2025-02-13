import logging

debug = False


def mute_logging_for_tests():
    global debug
    debug = True


def setup_logging():
    if not debug:
        # Initialize Logfire
        import logfire

        logfire.configure()

        logging.basicConfig(
            handlers=[logfire.LogfireLoggingHandler()], level=logging.DEBUG
        )
        logfire.install_auto_tracing(
            modules=["app.database", "app.handlers"],
            min_duration=0.01,
            check_imported_modules="ignore",
        )


# Silence known chatty loggers
CHATTY_LOGGERS = ["hpack.hpack", "httpcore.http2", "httpcore.connection"]
for logger_name in CHATTY_LOGGERS:
    logging.getLogger(logger_name).setLevel(logging.WARNING)
