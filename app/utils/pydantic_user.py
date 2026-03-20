from pydantic import BaseModel
from uuid import UUID


class UserCreate(BaseModel):
    name: str
    email: str
    password: str

class UserRead(BaseModel):
    id: UUID
    name: str
    email: str