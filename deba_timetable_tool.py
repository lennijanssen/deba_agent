from dotenv import load_dotenv
import os
import requests
from datetime import datetime
import xmltodict
from urllib.parse import quote
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain import hub
from langchain.agents import create_react_agent, AgentExecutor, tool



# --------- Loading variables from .env and getting ID and API Key ---------
load_dotenv()

llm = ChatOpenAI(model = 'gpt-4o-mini')

DB_CLIENT_ID = os.getenv("DB_CLIENT_ID")
DB_API_KEY   = os.getenv("DB_CLIENT_API_KEY")

if not DB_CLIENT_ID or not DB_API_KEY:
    raise RuntimeError("DB_CLIENT_ID or DB_API_KEY not set. Did you create the .env file?")

BASE_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"

HEADERS = {
    "DB-Client-Id": DB_CLIENT_ID,
    "DB-Api-Key": DB_API_KEY,
    "Accept": "application/xml"
}

# --------- DB API Helper Functions ---------

def search_station(pattern: str) -> str:
    """Look up EVA number for a station name."""
    url = f"{BASE_URL}/station/{quote(pattern)}"
    request = requests.get(url, headers=HEADERS, timeout = 20)
    request.raise_for_status()
    eva = xmltodict.parse(request.text)["stations"]["station"]["@eva"]
    return eva

def get_plan(eva: str, when: datetime) -> str:
    """Fetch timetable plan XML for given EVA + datetime."""
    yymmdd = when.strftime("%y%m%d")
    hour   = when.strftime("%H")
    url = f"{BASE_URL}/plan/{eva}/{yymmdd}/{hour}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text  # XML string

def parse_data(plan: str):
    """
    Return list of departures as tuples:
    (dep_dt, destination, HH:MM, category)
    Skips services without a usable time or destination/category.
    """
    doc = xmltodict.parse(plan)
    tt = doc.get("timetable", {}) or {}
    services = tt.get("s", []) or []
    if isinstance(services, dict):
        services = [services]

    rows = []

    for s in services:
        tl = s.get("tl", {}) or {}
        dp = s.get("dp", {}) or {}
        pt = dp.get("@pt")  # YYMMDDHHMM

        if not pt:
            continue

    # category (ICE/IC/RE/RB/S/... or operator)
        cat = (tl.get("@c") or "").strip()
        if not cat:
            continue  # skip this service

    # destination: prefer @pde, else last of @ppth
        dest = dp.get("@pde")
        if not dest:
            path = dp.get("@ppth") or ""
            if path:
                dest = path.split("|")[-1]
        if not dest:
            continue  # skip this service

    # time
        dep_dt = datetime.strptime(pt, "%y%m%d%H%M")
        hhmm = dep_dt.strftime("%H:%M")
        if not isinstance(pt, str):
            continue  # skip this service

        rows.append((dep_dt, dest, hhmm, cat))

        # sort chronologically
    rows.sort(key=lambda x: x[0])
    return rows


# --------- Langchain Tool ---------

@tool("db_departures", return_direct=True)
def db_departures(
    station_name : str,
    date_iso : str = None,
    hour_24: int = None,
) -> str:
    """
    Get a departure board for a station/hour from Deutsche Bahn Timetables.

    Args:
        station_name: e.g., "Dresden Hbf".
        date_iso: optional date in YYYY-MM-DD; defaults to today's date.
        hour_24: optional hour (0-23); defaults to current hour.

    Returns:
        A plain-text table: Destination | HH:MM | Train
    """

    # figure out the datetime slice
    now = datetime.now()
    if date_iso:
        try:
            base_date = datetime.strptime(date_iso, "%Y-%m-%d").date()
        except ValueError:
            return f"Invalid date '{date_iso}'. Use YYYY-MM-DD."
    else:
        base_date = now.date()

    if hour_24 is None:
        hour_24 = now.hour
    if not (0 <= int(hour_24) <= 23):
        return f"Invalid hour '{hour_24}'. Use 0-23."

    dt = datetime.strptime(f"{base_date} {int(hour_24)}", "%Y-%m-%d %H")

    # call DB
    try:
        eva = search_station(station_name)
    except requests.HTTPError as e:
        return f"Station lookup failed ({e.response.status_code})."
    except Exception as e:
        return f"Station lookup failed: {e}"

    try:
        plan = get_plan(eva, dt)
    except requests.HTTPError as e:
        body = getattr(e.response, "text", "") or ""
        return f"/plan failed ({e.response.status_code}). Body:\n{body[:400]}"
    except Exception as e:
        return f"/plan call failed: {e}"

    rows = parse_data(plan)

    # ✅ Build a plain-text table and RETURN it (don’t print)
    if not rows:
        return f"Keine Abfahrten gefunden für {station_name} um {dt.strftime('%H:00')}."

    lines = [
        f"Abfahrten für {station_name} ({dt.strftime('%Y-%m-%d %H:00')}):",
        "Ziel                 | Zeit  | Zug",
        "-" * 35,
    ]
    for _, dest, hhmm, cat in rows[:12]:  # cap to 12 lines for readability
        lines.append(f"{dest[:20]:<20} | {hhmm:>5} | {cat}")

    if len(rows) > 12:
        lines.append(f"... und {len(rows) - 12} weitere")

    return "\n".join(lines)



# ------- Legacy Code -------------- Legacy Code ---------- Legacy Code -------------


# # Questionnaire for getting departures from the desired station with train type

# if __name__ == "__main__":

# # Questions (adjustable)
#     station_name = input("Station name: ")
#     # date_str     = input("Date (YYYY-MM-DD): ")
#     # hour_str     = input("Hour (00-23): ")

#     # station_name = "Dresden Hbf"
#     date_str     = datetime.today().date()
#     hour_str     = datetime.now().hour


# # Adjusting time format for the API take it in and work appropriately
#     dt = datetime.strptime(f"{date_str} {hour_str}", "%Y-%m-%d %H")

# # Finding EVA number of train station
#     eva = search_station(station_name)
#     print(f"EVA for {station_name}: {eva}")

# # Getting the departure and arrival info for the station
#     plan = xmltodict.parse(get_plan(eva, dt))
#     services = plan['timetable']["s"]

#     rows=[]

# # Loop to filter out information for each training leaving the station
#     for service in services:
#         tl = service.get("tl", {})
#         dp = service.get("dp", {})

#     # Prefer explicit destination if available
#         dest = dp.get("@pde")
#         if not dest:
#             path = dp.get("@ppth") or ""
#             if path:
#                 dest = path.split("|")[-1]

#     # Get planned departure time for each train
#         time = dp.get("@pt")
#         hhmm = None
#         dt_obj = None
#         if time and len(time) == 10:  # YYMMDDHHMM
#             dt_obj = datetime.strptime(time, "%y%m%d%H%M")
#             hhmm = dt_obj.strftime("%H:%M")


#     # I also want the train category
#         cat = tl.get("@c")

#         if dest and hhmm and cat:
#             rows.append((dt_obj, dest, hhmm, cat))


#     # Sort trains by departure time
#     rows.sort(key=lambda x: x[0])


#     # print the table
# print("Departures: ")
# for _, dest, hhmm, cat, in rows:
#     print(f"{dest:<20} | {hhmm} | {cat}")
