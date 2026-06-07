# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, status
from app.schemas.user import UserRegister, UserLogin, Token, UserResponse
from app.database import users_collection
from app.services.auth import hash_password, verify_password, create_access_token

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_in: UserRegister):
    # Check if user already exists (case-insensitive for safety)
    existing_user = users_collection.find_one({"username": {"$regex": f"^{user_in.username}$", "$options": "i"}})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered."
        )
    
    hashed_pwd = hash_password(user_in.password)
    user_doc = {
        "username": user_in.username,
        "password_hash": hashed_pwd
    }
    
    result = users_collection.insert_one(user_doc)
    created_id = str(result.inserted_id)
    
    return UserResponse(id=created_id, username=user_in.username)

@router.post("/login", response_model=Token)
def login(user_in: UserLogin):
    user = users_collection.find_one({"username": user_in.username})
    if not user or not verify_password(user_in.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect username or password."
        )
    
    user_id = str(user["_id"])
    access_token = create_access_token(data={"sub": user_id})
    
    return Token(access_token=access_token, token_type="bearer")
