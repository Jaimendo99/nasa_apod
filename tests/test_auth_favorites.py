import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch, AsyncMock
import asyncio

from main import app, get_db
from database import Base, User
from auth import get_password_hash

# Setup a shared in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # Use StaticPool to ensure all sessions use the same connection
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override the get_db dependency for the app
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="function")
def db_setup_and_teardown():
    """Create and drop database tables for each test function for isolation."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="module")
def client():
    """A TestClient that uses the overridden database dependency."""
    return TestClient(app)

@pytest.fixture
def mock_nasa_api():
    """Mock the NASA APOD API call."""
    with patch('main.get_nasa_apod_data', new_callable=AsyncMock) as mock_get:
        async def side_effect(date=None):
            if date == "2025-07-01":
                return {"title": "July 1st APOD", "date": "2025-07-01", "media_type": "image", "url": "", "explanation": ""}
            return {"title": "Default APOD", "date": "2025-07-06", "media_type": "image", "url": "", "explanation": ""}
        mock_get.side_effect = side_effect
        yield

# --- Auth Tests ---
def test_signup_and_login(client, db_setup_and_teardown):
    # Sign up a new user and don't follow the redirect
    response = client.post("/signup", data={"username": "testuser", "password": "testpass"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    # Log in with the new user and don't follow the redirect
    response = client.post("/login", data={"username": "testuser", "password": "testpass"}, follow_redirects=False)
    assert response.status_code == 303
    assert "access_token" in response.cookies

# --- Go to Date Test ---
def test_go_to_date(client, db_setup_and_teardown, mock_nasa_api):
    response = client.get("/?date=2025-07-01")
    assert response.status_code == 200
    assert "July 1st APOD" in response.text

# --- Favorites Tests ---
@pytest.fixture
def authenticated_client(client, db_setup_and_teardown):
    """Return a client that is authenticated as 'favuser'."""
    client.post("/signup", data={"username": "favuser", "password": "favpass"}, follow_redirects=True)
    client.post("/login", data={"username": "favuser", "password": "favpass"}, follow_redirects=True)
    return client

def test_add_and_remove_favorite(authenticated_client, mock_nasa_api):
    # Add a favorite
    response = authenticated_client.post("/favorite", data={"apod_date": "2025-07-06"}, follow_redirects=False)
    assert response.status_code == 303

    # Check if it's favorited by following the redirect
    response = authenticated_client.get("/?date=2025-07-06")
    assert "Unfavorite" in response.text

    # Remove the favorite
    response = authenticated_client.post("/favorite", data={"apod_date": "2025-07-06"}, follow_redirects=False)
    assert response.status_code == 303

    # Check it's no longer a favorite
    response = authenticated_client.get("/?date=2025-07-06")
    assert "Favorite" in response.text

def test_view_favorites_page(authenticated_client, mock_nasa_api):
    # Add a favorite
    authenticated_client.post("/favorite", data={"apod_date": "2025-07-01"}, follow_redirects=True)

    with patch('main.asyncio.gather', new_callable=AsyncMock) as mock_gather:
        mock_gather.return_value = [
            type('obj', (object,), {'json': lambda: {"title": "July 1st APOD"}})
        ]
        response = authenticated_client.get("/favorites")
        assert response.status_code == 200
        assert "My Favorites" in response.text
        assert "July 1st APOD" in response.text