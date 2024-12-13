from pydantic import BaseModel
import datetime


class UserCreate(BaseModel):
    email: str
    password: str


class BookRequest(BaseModel):
    book_id: int
    start_date: str
    end_date: str


class BorrowRequestOut(BaseModel):
    id: int
    book_id: int
    book_title: str
    start_date: str
    end_date: str
    status: str


class BookOut(BaseModel):
    id: int
    title: str
    author: str
    copies_available: int
