from typing import Protocol, List, Optional, Set
from jobbot.models import Job

class JobSource(Protocol):
    name: str

    def list_jobs(self, max_pages: Optional[int] = None, known_ids: Optional[Set[str]] = None) -> List[Job]:
        ...

    def fetch_detail(self, job: Job) -> Job:
        ...
