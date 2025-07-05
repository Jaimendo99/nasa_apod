
import os
from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

app = FastAPI()

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

def get_nasa_apod_data(date: str = None):
    api_key = os.getenv("NASA_API_KEY", "DEMO_KEY")
    url = f"https://api.nasa.gov/planetary/apod?api_key={api_key}"
    if date:
        url += f"&date={date}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

@app.get("/")
async def read_root(request: Request, date: str = None):
    try:
        if date:
            try:
                current_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                return templates.TemplateResponse(request, "index.html", {"error": "Invalid date format. Please use YYYY-MM-DD."})
        else:
            current_date = datetime.now().date()

        apod_data = get_nasa_apod_data(current_date.strftime("%Y-%m-%d"))
        
        prev_date = (current_date - timedelta(days=1)).strftime("%Y-%m-%d")
        next_date = (current_date + timedelta(days=1)).strftime("%Y-%m-%d")
        
        return templates.TemplateResponse(request, "index.html", {
            "apod_data": apod_data,
            "date": current_date.strftime("%Y-%m-%d"),
            "prev_date": prev_date,
            "next_date": next_date
        })
    except requests.exceptions.RequestException as e:
        return templates.TemplateResponse(request, "index.html", {"error": str(e)})
