import os
import httpx
import asyncio
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from database import SessionLocal, User, Favorite, engine, Base
from auth import get_password_hash, verify_password, create_access_token, get_current_user
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

@app.on_event("startup")
def on_startup():
    os.makedirs("/app/data", exist_ok=True)
    Base.metadata.create_all(bind=engine)

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_nasa_apod_data(date: str = None):
    api_key = os.getenv("NASA_API_KEY", "DEMO_KEY")
    url = f"https://api.nasa.gov/planetary/apod?api_key={api_key}"
    if date:
        url += f"&date={date}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

@app.get("/")
async def read_root(request: Request, date: str = None, db: Session = Depends(get_db)):
    try:
        user = None
        try:
            token = request.cookies.get("access_token")
            if token:
                user = get_current_user(token.split(" ")[1], db)
        except Exception:
            pass

        if date:
            try:
                current_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                return templates.TemplateResponse("index.html", {"request": request, "error": "Invalid date format. Please use YYYY-MM-DD."})
        else:
            current_date = datetime.utcnow().date()

        try:
            apod_data = await get_nasa_apod_data(current_date.strftime("%Y-%m-%d"))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return templates.TemplateResponse("index.html", {"request": request, "error": f"No APOD found for {current_date.strftime('%Y-%m-%d')}."})
            else:
                raise e

        prev_date = (current_date - timedelta(days=1)).strftime("%Y-%m-%d")
        next_date = (current_date + timedelta(days=1)).strftime("%Y-%m-%d")

        is_favorite = False
        if user:
            favorite = db.query(Favorite).filter_by(owner_id=user.id, apod_date=current_date).first()
            if favorite:
                is_favorite = True

        return templates.TemplateResponse("index.html", {
            "request": request,
            "apod_data": apod_data,
            "date": current_date.strftime("%Y-%m-%d"),
            "prev_date": prev_date,
            "next_date": next_date,
            "user": user,
            "is_favorite": is_favorite
        })
    except httpx.RequestError as e:
        return templates.TemplateResponse("index.html", {"request": request, "error": str(e)})

@app.get("/signup")
async def signup_form(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.post("/signup")
async def signup(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if user:
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Username already exists"})

    hashed_password = get_password_hash(password)
    new_user = User(username=username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return RedirectResponse(url="/login", status_code=303)

@app.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(response: Response, request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password"})

    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    return response

@app.post("/favorite")
async def add_favorite(request: Request, apod_date: str = Form(...), db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(token.split(" ")[1], db)
    date_obj = datetime.strptime(apod_date, "%Y-%m-%d").date()

    favorite = db.query(Favorite).filter_by(owner_id=user.id, apod_date=date_obj).first()
    if favorite:
        db.delete(favorite)
        db.commit()
    else:
        new_favorite = Favorite(apod_date=date_obj, owner_id=user.id)
        db.add(new_favorite)
        db.commit()

    return RedirectResponse(url=f"/?date={apod_date}", status_code=303)

@app.get("/favorites")
async def favorites(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(token.split(" ")[1], db)
    favorites = db.query(Favorite).filter_by(owner_id=user.id).all()

    async with httpx.AsyncClient() as client:
        tasks = []
        for fav in favorites:
            date_str = fav.apod_date.strftime("%Y-%m-%d")
            api_key = os.getenv("NASA_API_KEY", "DEMO_KEY")
            url = f"https://api.nasa.gov/planetary/apod?api_key={api_key}&date={date_str}"
            tasks.append(client.get(url))

        responses = await asyncio.gather(*tasks)

    apods = [res.json() for res in responses]

    return templates.TemplateResponse("favorites.html", {"request": request, "apods": apods, "user": user})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0.0", port=8000)
