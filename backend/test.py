import os
from dotenv import load_dotenv
import requests

load_dotenv()
MAP_KEY = os.environ.get("FIRMS_MAP_KEY")
if not MAP_KEY:
    raise RuntimeError("FIRMS_MAP_KEY environment variable is not set")

url = (
    f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
    f"{MAP_KEY}/VIIRS_NOAA20_NRT/68,6,97,36/1"
)

response = requests.get(url)

print("Status:", response.status_code)
print(response.text[:2000])