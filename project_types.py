from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class LectureEntry(BaseModel):
    id: Optional[int] = None
    session_type: Literal["lecture", "officehours"]
    session_number: int
    speaker_name: str
    timestamp: str
    content: str


class LectureScenario(BaseModel):
    id: int
    question: str
    answer: str
    entry_ids: List[int]  # Database IDs of relevant lecture entries
    session_type: Literal["lecture", "officehours"]  # Context for the query
    session_number: int  # Which session this scenario is about
    timestamp_context: Optional[str] = None  # Optional time context like "around 15:00"
    how_realistic: float = Field(
        ..., 
        description="Score between 0 and 1 on how realistic this question is"
    )
    split: Literal["train", "test"]