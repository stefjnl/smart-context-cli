from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import sqlite3

app = FastAPI()

class User(BaseModel):
    id: int = None
    name: str
    email: str

@app.get("/")
def read_root():
    return {"message": "Hello FastAPI"}

@app.get("/users", response_model=List[User])
def get_users():
    # TODO: Implement database query
    return []

@app.post("/users")
def create_user(user: User):
    # TODO: Add to database
    return {"message": f"User {user.name} created"}