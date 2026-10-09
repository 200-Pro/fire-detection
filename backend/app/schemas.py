from typing import Literal
from pydantic import BaseModel, Field

class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=16, max_length=256)

class CameraInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    location: str = Field(default="", max_length=100)
    kind: Literal["browser", "edge"] = "browser"

class CameraUpdate(BaseModel):
    enabled: bool

class PairInput(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^[A-Z0-9]{8}$")

class AlertUpdate(BaseModel):
    state: Literal["acknowledged", "resolved"]
    note: str = Field(default="", max_length=1000)
