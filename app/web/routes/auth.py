"""
NEXUS WALLET - Authentication Routes
"""

from fastapi import APIRouter, Request, Form, HTTPException, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from passlib.hash import bcrypt
from datetime import datetime, timedelta
import secrets
import os

from web.database import UserDB

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Session storage (in production use Redis)
sessions = {}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    sessions[token] = {
        "user_id": user_id,
        "expires": datetime.now() + timedelta(days=7)
    }
    return token


def get_current_user(request: Request) -> dict:
    token = request.cookies.get("session_token")
    if not token or token not in sessions:
        return None
    
    session = sessions[token]
    if datetime.now() > session["expires"]:
        del sessions[token]
        return None
    
    return session


async def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/login")
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/wallet/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    user = await UserDB.get_user_by_username(username)
    
    if not user or not bcrypt.verify(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password"
        })
    
    token = create_session(user["id"])
    await UserDB.update_last_login(user["id"])
    
    response = RedirectResponse(url="/wallet/dashboard", status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=7 * 24 * 60 * 60,
        samesite="lax"
    )
    return response


@router.get("/register")
async def register_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/wallet/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    email: str = Form(None)
):
    errors = []
    
    if len(username) < 3:
        errors.append("Username must be at least 3 characters")
    
    if len(password) < 6:
        errors.append("Password must be at least 6 characters")
    
    if password != password_confirm:
        errors.append("Passwords do not match")
    
    existing = await UserDB.get_user_by_username(username)
    if existing:
        errors.append("Username already taken")
    
    if errors:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "errors": errors,
            "username": username,
            "email": email
        })
    
    password_hash = bcrypt.hash(password)
    user_id = await UserDB.create_user(username, password_hash, email)
    
    token = create_session(user_id)
    
    response = RedirectResponse(url="/wallet/dashboard", status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=7 * 24 * 60 * 60,
        samesite="lax"
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token and token in sessions:
        del sessions[token]
    
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session_token")
    return response