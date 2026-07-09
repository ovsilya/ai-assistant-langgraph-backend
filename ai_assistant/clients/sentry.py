import sentry_sdk

from config import APP_VERSION, ENVIRONMENT, SENTRY_DSN


def configure_sentry() -> None:
    if not SENTRY_DSN:
        return

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENVIRONMENT,
        release=APP_VERSION,
    )
