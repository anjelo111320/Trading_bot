from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class OwnerView(BaseModel):
    email: str
    role: str


class TicketView(BaseModel):
    ticket: str
    expires_in_seconds: int
