from typing import Protocol, List, Optional
from jobbot.models import Job

class JobSource(Protocol):
    name: str

    def list_jobs(self, max_pages: Optional[int] = None) -> List[Job]:
        ...

    def fetch_detail(self, job: Job) -> Job:
        ...
