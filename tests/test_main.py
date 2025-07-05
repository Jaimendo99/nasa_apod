import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from main import app
import requests

client = TestClient(app)

@pytest.fixture
def mock_nasa_api_success():
    with patch('main.get_nasa_apod_data') as mock_get:
        mock_get.return_value = {
            "copyright":"Alberto Pisabarro",
            "date":"2025-07-04",
            "explanation":"Face-on spiral galaxy NGC 6946 and open star cluster NGC 6939 share this cosmic snapshot...",
            "hdurl":"https://apod.nasa.gov/apod/image/2507/N6946N6939pisabarro.jpg",
            "media_type":"image",
            "service_version":"v1",
            "title":"NGC 6946 and NGC 6939",
            "url":"https://apod.nasa.gov/apod/image/2507/N6946N6939pisabarro1024.jpg"
        }
        yield

@pytest.fixture
def mock_nasa_api_failure():
    with patch('main.get_nasa_apod_data') as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException("Failed to fetch data from NASA API")
        yield

def test_read_root_success(mock_nasa_api_success):
    response = client.get("/")
    assert response.status_code == 200
    assert "NGC 6946 and NGC 6939" in response.text

def test_read_root_failure(mock_nasa_api_failure):
    response = client.get("/")
    assert response.status_code == 200
    assert "Error: Failed to fetch data from NASA API" in response.text


def test_read_root_with_date(mock_nasa_api_success):
    response = client.get("/?date=2025-07-04")
    assert response.status_code == 200
    assert "NGC 6946 and NGC 6939" in response.text


def test_date_navigation(mock_nasa_api_success):
    response = client.get("/?date=2025-07-04")
    assert response.status_code == 200
    assert "/?date=2025-07-03" in response.text
    assert "/?date=2025-07-05" in response.text


def test_invalid_date_format():
    response = client.get("/?date=invalid-date")
    assert response.status_code == 200
    assert "Invalid date format. Please use YYYY-MM-DD." in response.text


def test_static_file():
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


@pytest.fixture
def mock_nasa_api_video():
    with patch('main.get_nasa_apod_data') as mock_get:
        mock_get.return_value = {
            "date": "2025-07-03",
            "explanation": "This is a video of a black hole.",
            "media_type": "video",
            "title": "Black Hole Video",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        }
        yield


def test_read_root_video(mock_nasa_api_video):
    response = client.get("/?date=2025-07-03")
    assert response.status_code == 200
    assert "Black Hole Video" in response.text
    assert "video" in response.text
