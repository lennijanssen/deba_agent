from dotenv import load_dotenv
import os
import requests
from datetime import datetime
import xmltodict
from urllib.parse import quote
from datetime import datetime



# Loading variables from .env and getting ID and API Key

load_dotenv()

DB_CLIENT_ID = os.getenv("DB_CLIENT_ID")
DB_API_KEY   = os.getenv("DB_CLIENT_API_KEY")

if not DB_CLIENT_ID or not DB_API_KEY:
    raise RuntimeError("DB_CLIENT_ID or DB_API_KEY not set. Did you create the .env file?")

# Endpoint to access DB timetable data, plus headers needed for the URL

BASE_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"

HEADERS = {
    "DB-Client-Id": DB_CLIENT_ID,
    "DB-Api-Key": DB_API_KEY,
    "Accept": "application/xml"
}
#  Description inside function
def search_station(pattern: str) -> str:
    """Look up EVA number for a station name."""
    url = f"{BASE_URL}/station/{quote(pattern)}"
    request = requests.get(url, headers=HEADERS, timeout = 20)
    request.raise_for_status()
    eva = xmltodict.parse(request.text)["stations"]["station"]["@eva"]
    return eva

# Description inside function
def get_plan(eva: str, when: datetime) -> str:
    """Fetch timetable plan XML for given EVA + datetime."""
    yymmdd = when.strftime("%y%m%d")
    hour   = when.strftime("%H")
    url = f"{BASE_URL}/plan/{eva}/{yymmdd}/{hour}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text  # XML string


# Questionnaire for getting departures from the desired station with train type

if __name__ == "__main__":

# Questions (adjustable)
    station_name = input("Station name: ")
    # date_str     = input("Date (YYYY-MM-DD): ")
    # hour_str     = input("Hour (00-23): ")

    # station_name = "Dresden Hbf"
    date_str     = datetime.today().date()
    hour_str     = datetime.now().hour


# Adjusting time format for the API take it in and work appropriately
    dt = datetime.strptime(f"{date_str} {hour_str}", "%Y-%m-%d %H")

# Finding EVA number of train station
    eva = search_station(station_name)
    print(f"EVA for {station_name}: {eva}")

# Getting the departure and arrival info for the station
    plan = xmltodict.parse(get_plan(eva, dt))
    services = plan['timetable']["s"]

    rows=[]

# Loop to filter out information for each training leaving the station
    for service in services:
        tl = service.get("tl", {})
        dp = service.get("dp", {})

    # Prefer explicit destination if available
        dest = dp.get("@pde")
        if not dest:
            path = dp.get("@ppth") or ""
            if path:
                dest = path.split("|")[-1]

    # Get planned departure time for each train
        time = dp.get("@pt")
        hhmm = None
        dt_obj = None
        if time and len(time) == 10:  # YYMMDDHHMM
            dt_obj = datetime.strptime(time, "%y%m%d%H%M")
            hhmm = dt_obj.strftime("%H:%M")


    # I also want the train category
        cat = tl.get("@c")

        if dest and hhmm and cat:
            rows.append((dt_obj, dest, hhmm, cat))


    # Sort trains by departure time
    rows.sort(key=lambda x: x[0])


    # print the table
    print("\Departues: ")
    for _, dest, hhmm, cat, in rows:
        print(f"{dest:<20} | {hhmm} | {cat}")
