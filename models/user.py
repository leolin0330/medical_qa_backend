from pydantic import BaseModel
from utils.security import hash_password


class UserLogin(BaseModel):
    username: str
    password: str


fake_user_db = {
    "admin": {
        "username": "admin",
        "password": hash_password("123456")
    }
}