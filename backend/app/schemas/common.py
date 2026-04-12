from pydantic import BaseModel


class UserContext(BaseModel):
    username: str
    role: str
    asset_group_ids: list[str]
