from uuid import UUID


class RecordingQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def index_source(self, source_id: UUID) -> None:
        self.calls.append(("index", source_id))

    async def embed_revision(self, revision_id: UUID, space_id: int) -> None:
        self.calls.append(("embed", (revision_id, space_id)))

    async def reconcile(self, run_id: int) -> bool:
        self.calls.append(("reconcile", run_id))
        return True

    async def reset_stalled(self, seconds_since_heartbeat: int) -> int:
        self.calls.append(("reset_stalled", seconds_since_heartbeat))
        return 0
