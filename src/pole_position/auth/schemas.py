from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    # POST /api/auth/register
    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9_]+$",
    )
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    # POST /api/auth/login
    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9_]+$",
    )
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    # POST /api/auth/login
    access_token: str
    token_type: str = "bearer"
