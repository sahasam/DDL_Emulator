import logging


def configure_logging():
    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,

        'formatters': {
            'standard': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            },
        },

        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'level': 'DEBUG',
            },
        },

        'loggers': {
            'Port.alice': {
                'level': 'DEBUG',
                'handlers': ['console'],
                'propagate': False,
            },
            'Port.bob': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False,
            },
            'Port.charlie': {
                'level': 'DEBUG',
                'handlers': [],  # No stream handler attached
                'propagate': False,
            },
        },

        'root': {
            'level': 'WARNING',
            'handlers': [],
        },
    })