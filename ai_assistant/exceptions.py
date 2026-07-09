"""Domain exceptions for the AI Assistant service."""


class ConversationNotFoundError(Exception):
    """Raised when an operation targets a conversation that does not exist."""

    def __init__(self, user_id: str, conversation_id: str) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        super().__init__(
            f"conversation {conversation_id} not found for user {user_id}",
        )


class ConversationAlreadyExistsError(Exception):
    """Raised when creating a conversation whose id already exists for the user."""

    def __init__(self, user_id: str, conversation_id: str) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        super().__init__(
            f"conversation {conversation_id} already exists for user {user_id}",
        )


class DeletionLeaseLostError(Exception):
    """Raised when a deletion-job write fails the ``lease_owner`` condition."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"lost lease on deletion job {job_id}")
