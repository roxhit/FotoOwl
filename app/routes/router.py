from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from app.config.db import *
from app.models.models import User, Book, BorrowRequest
from app.schemas.schemas import UserCreate, BookRequest, BorrowRequestOut, BookOut
from typing import List
import csv
from io import StringIO
import re

router = APIRouter()
security = HTTPBasic()


async def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)
):
    """
    Retrieves the current user from the database based on provided credentials.

    Parameters:
        credentials (HTTPBasicCredentials): The HTTPBasicCredentials containing the username and password.
        db (Session): The database session.

    Returns:
        User: The user object if authentication is successful.

    Raises:
        HTTPException: If the user credentials are invalid or the user does not exist.
    """
    user = db.query(User).filter(User.email == credentials.username).first()
    if not user or user.password != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


@router.post("/admin/users", status_code=status.HTTP_201_CREATED)
def create_user(
    user: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Creates a new user if the current user has admin privileges.

    Parameters:
        user (UserCreate): The data for creating the new user.
        current_user (User): The currently authenticated user.
        db (Session): The database session.

    Returns:
        dict: A success message with the ID of the newly created user.

    Raises:
        HTTPException: If the user does not have admin privileges, if the email format is invalid,
                        if the password is too short, or if the user already exists.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    if "@" not in user.email:
        raise HTTPException(status_code=400, detail="Invalid email format")

    if len(user.password) < 6:
        raise HTTPException(
            status_code=400, detail="Password must be at least 6 characters"
        )

    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    new_user = User(email=user.email, password=user.password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "User created successfully", "user_id": new_user.id}


@router.get("/admin/requests", response_model=List[BorrowRequestOut])
def view_borrow_requests(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Retrieves a list of all borrow requests if the current user has admin privileges.

    Parameters:
        current_user (User): The currently authenticated user.
        db (Session): The database session.

    Returns:
        List[BorrowRequestOut]: A list of borrow requests with their details.

    Raises:
        HTTPException: If the current user does not have admin privileges.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    requests = db.query(BorrowRequest).all()
    return [
        {
            "id": req.id,
            "book_id": req.book_id,
            "book_title": req.book.title,
            "start_date": req.start_date.isoformat(),
            "end_date": req.end_date.isoformat(),
            "status": req.status,
        }
        for req in requests
    ]


@router.post("/admin/requests/{request_id}")
def approve_or_deny_request(
    request_id: int,
    action: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Approves or denies a borrow request based on the provided action.

    Parameters:
        request_id (int): The ID of the borrow request.
        action (str): The action to take on the request ("approve" or "deny").
        current_user (User): The currently authenticated user.
        db (Session): The database session.

    Returns:
        dict: A success message indicating the action taken on the request.

    Raises:
        HTTPException: If the current user does not have admin privileges,
                        if the request does not exist, if the action is invalid,
                        or if the book is already borrowed during the requested period.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    borrow_request = (
        db.query(BorrowRequest).filter(BorrowRequest.id == request_id).first()
    )
    if not borrow_request:
        raise HTTPException(status_code=404, detail="Request not found")

    if action not in ["approve", "deny"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    if action == "approve":
        if borrow_request.status != "Pending":
            raise HTTPException(status_code=400, detail="Request already processed")

        overlapping = (
            db.query(BorrowRequest)
            .filter(
                BorrowRequest.book_id == borrow_request.book_id,
                BorrowRequest.status == "Approved",
                BorrowRequest.start_date <= borrow_request.end_date,
                BorrowRequest.end_date >= borrow_request.start_date,
            )
            .first()
        )
        if overlapping:
            raise HTTPException(
                status_code=400, detail="Book already borrowed during this period"
            )

        borrow_request.status = "Approved"
        book = db.query(Book).filter(Book.id == borrow_request.book_id).first()
        if book:
            book.copies_available -= 1

    elif action == "deny":
        borrow_request.status = "Denied"

    db.commit()
    return {"message": f"Request {action}d successfully"}


@router.get("/admin/users/{user_id}/history")
def view_user_history(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves the borrowing history of a specific user if the current user has admin privileges.

    Parameters:
        user_id (int): The ID of the user whose history is to be retrieved.
        current_user (User): The currently authenticated user.
        db (Session): The database session.

    Returns:
        List[dict]: A list of borrow request details for the user.

    Raises:
        HTTPException: If the current user does not have admin privileges or if the user does not exist.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    requests = db.query(BorrowRequest).filter(BorrowRequest.user_id == user_id).all()
    return [
        {
            "book_title": req.book.title,
            "start_date": req.start_date.isoformat(),
            "end_date": req.end_date.isoformat(),
            "status": req.status,
        }
        for req in requests
    ]


@router.get("/books", response_model=List[BookOut])
def get_books(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Retrieves a list of all books in the library.

    Parameters:
        current_user (User): The currently authenticated user.
        db (Session): The database session.

    Returns:
        List[BookOut]: A list of books with their details.
    """
    books = db.query(Book).all()
    return books


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def submit_request(
    request: BookRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submits a borrow request for a specific book.

    Parameters:
        request (BookRequest): The data for the borrow request.
        current_user (User): The currently authenticated user.
        db (Session): The database session.

    Returns:
        dict: A success message with the ID of the newly created borrow request.

    Raises:
        HTTPException: If the book is not available or if the book is already borrowed during the requested period.
    """
    book = db.query(Book).filter(Book.id == request.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.copies_available <= 0:
        raise HTTPException(status_code=400, detail="No copies available")

    overlapping = (
        db.query(BorrowRequest)
        .filter(
            BorrowRequest.book_id == book.id,
            BorrowRequest.status == "Approved",
            BorrowRequest.start_date <= request.end_date,
            BorrowRequest.end_date >= request.start_date,
        )
        .first()
    )
    if overlapping:
        raise HTTPException(
            status_code=400, detail="Book already borrowed during this period"
        )

    borrow_request = BorrowRequest(
        user_id=current_user.id,
        book_id=book.id,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    db.add(borrow_request)
    db.commit()
    db.refresh(borrow_request)
    return {
        "message": "Request submitted successfully",
        "request_id": borrow_request.id,
    }


@router.get("/history")
def view_personal_history(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Retrieves the borrowing history of the currently authenticated user.

    Parameters:
        current_user (User): The currently authenticated user.
        db (Session): The database session.

    Returns:
        List[dict]: A list of borrow request details for the authenticated user.
    """
    requests = (
        db.query(BorrowRequest).filter(BorrowRequest.user_id == current_user.id).all()
    )
    return [
        {
            "book_title": req.book.title,
            "start_date": req.start_date.isoformat(),
            "end_date": req.end_date.isoformat(),
            "status": req.status,
        }
        for req in requests
    ]


@router.get("/download-history")
def download_history(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Downloads the borrow history of the currently authenticated user as a CSV file.

    Parameters:
        current_user (User): The currently authenticated user.
        db (Session): The database session.

    Returns:
        dict: A dictionary containing the CSV data of the borrow history.
    """
    requests = (
        db.query(BorrowRequest).filter(BorrowRequest.user_id == current_user.id).all()
    )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Book Title", "Start Date", "End Date", "Status"])
    for req in requests:
        writer.writerow([req.book.title, req.start_date, req.end_date, req.status])

    output.seek(0)
    return {"csv": output.getvalue()}
