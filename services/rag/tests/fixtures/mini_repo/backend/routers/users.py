from fastapi import APIRouter

router = APIRouter(tags=["users"])

FAKE_USERS = [{"id": "u1", "name": "peco"}]


@router.get("/users")
def list_users():
    return FAKE_USERS


@router.get("/users/{user_id}")
def get_user(user_id: str):
    return next((u for u in FAKE_USERS if u["id"] == user_id), None)
