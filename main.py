import os
import httpx
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from database import SessionLocal, User, Favorite, engine, Base
from auth import get_password_hash, verify_password, create_access_token, get_current_user
from dotenv import load_dotenv
from prometheus_client import make_asgi_app

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application startup and shutdown tasks for the FastAPI app.
    
    On startup, creates the data directory and initializes database tables. On shutdown, performs any necessary cleanup.
    """
    logger.info("Application startup: Creating data directory and database tables")
    os.makedirs("/app/data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
    yield
    logger.info("Application shutdown")
    # Clean up resources on shutdown if needed

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Add prometheus asgi middleware to route /metrics requests
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_nasa_apod_data(date: str = None):
    """
    Fetch NASA's Astronomy Picture of the Day (APOD) data for a specified date asynchronously.
    
    Parameters:
        date (str, optional): The date in 'YYYY-MM-DD' format for which to retrieve APOD data. If not provided, retrieves data for the current day.
    
    Returns:
        dict: The JSON response containing APOD data from NASA's API.
    
    Raises:
        httpx.HTTPStatusError: If the API request returns an unsuccessful HTTP status.
        Exception: For any unexpected errors during the request.
    """
    api_key = os.getenv("NASA_API_KEY", "DEMO_KEY")
    url = f"https://api.nasa.gov/planetary/apod?api_key={api_key}"
    if date:
        url += f"&date={date}"

    logger.info(f"Fetching NASA APOD data for date: {date if date else 'today'}")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            logger.info(f"Successfully fetched NASA APOD data for date: {date if date else 'today'}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching NASA APOD data: {e.response.status_code} - {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching NASA APOD data: {e}")
            raise

@app.get("/")
async def read_root(request: Request, date: str = None, db: Session = Depends(get_db)):
    """
    Handles the root endpoint by displaying the NASA Astronomy Picture of the Day (APOD) for a specified date, with user authentication and favorite status support.
    
    If a date is provided, fetches the APOD for that date; otherwise, defaults to the current date. Authenticated users can see whether the APOD is marked as a favorite. Renders the main page with APOD data, navigation for previous and next dates, user info, and favorite status. Displays error messages for invalid dates or API errors.
    """
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
    """
    Handles user signup by creating a new user account if the username is not already taken.
    
    If the username exists, renders the signup form with an error message. On successful registration, redirects the user to the login page.
    """
    logger.info(f"User signup attempt for username: {username}")
    user = db.query(User).filter(User.username == username).first()
    if user:
        logger.warning(f"Signup failed - username already exists: {username}")
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Username already exists"})

    hashed_password = get_password_hash(password)
    new_user = User(username=username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info(f"New user created successfully: {username}")

    return RedirectResponse(url="/login", status_code=303)

@app.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(response: Response, request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """
    Authenticates a user and sets an access token cookie upon successful login.
    
    If the provided credentials are valid, issues a JWT access token with a 30-minute expiry and redirects to the home page. If authentication fails, renders the login page with an error message.
    """
    logger.info(f"Login attempt for username: {username}")
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        logger.warning(f"Failed login attempt for username: {username}")
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password"})

    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    logger.info(f"Successful login for username: {username}")
    return response

@app.get("/logout")
async def logout(response: Response):
    """
    Logs out the current user by deleting the access token cookie and redirecting to the home page.
    
    Returns:
        RedirectResponse: A redirect response to the root URL with the access token cookie removed.
    """
    logger.info("User logout")
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
    """
    Display the authenticated user's list of favorite NASA APOD entries.
    
    If the user is not authenticated, redirects to the login page. Fetches APOD data for each favorite date asynchronously and renders the favorites page with the retrieved entries.
    """
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(token.split(" ")[1], db)
    favorites = db.query(Favorite).filter_by(owner_id=user.id).all()

    logger.info(f"Fetching {len(favorites)} favorite APOD entries for user: {user.username}")
    async with httpx.AsyncClient() as client:
        tasks = []
        for fav in favorites:
            date_str = fav.apod_date.strftime("%Y-%m-%d")
            api_key = os.getenv("NASA_API_KEY", "DEMO_KEY")
            url = f"https://api.nasa.gov/planetary/apod?api_key={api_key}&date={date_str}"
            tasks.append(client.get(url))

        try:
            responses = await asyncio.gather(*tasks)
            logger.info(f"Successfully fetched all {len(responses)} favorite APOD entries")
        except Exception as e:
            logger.error(f"Error fetching favorite APOD entries: {e}")
            raise

    apods = [res.json() for res in responses]

    return templates.TemplateResponse("favorites.html", {"request": request, "apods": apods, "user": user})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
