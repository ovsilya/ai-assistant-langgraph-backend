from os import getenv

from .base import *  # noqa: F403

ENVIRONMENT = getenv("ENVIRONMENT", "").lower()

if ENVIRONMENT == "dev":
    from .dev import *  # noqa: F403
elif ENVIRONMENT == "test":
    from .test import *  # noqa: F403
