from pydantic import BaseModel, computed_field


class ApiKeySec(BaseModel):
    plain_key: str
    hashed_key: str

    @computed_field
    @property
    def obscured_key(self) -> str:
        return self.plain_key[:8] + '...' + self.plain_key[-3:]
