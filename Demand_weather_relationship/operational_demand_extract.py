import os
import requests
from datetime import datetime

# Base configuration
BASE_URL = "https://nemweb.com.au{year}/MMSDM_{year}_{month}/MMSDM_Historical_Data_Video/PUBLIC_DVD_DEMANDOPERATIONALACTUAL_{year}{month}010000.zip"
TARGET_DIR = "./aemo_operational_demand"
os.makedirs(TARGET_DIR, exist_ok=True)

# Time range constraints
START_YEAR, START_MONTH = 2016, 10
CURRENT_YEAR, CURRENT_MONTH = datetime.now().year, datetime.now().month

print(u"Starting AEMO DEMANDOPERATIONALACTUAL historical data download...")

# Loop through years and months
for year in range(START_YEAR, CURRENT_YEAR + 1):
    start_m = START_MONTH if year == START_YEAR else 1
    end_m = CURRENT_MONTH if year == CURRENT_YEAR else 12
    
    for month in range(start_m, end_m + 1):
        month_str = f"{month:02d}"
        file_url = BASE_URL.format(year=year, month=month_str)
        file_name = f"PUBLIC_DVD_DEMANDOPERATIONALACTUAL_{year}{month_str}010000.zip"
        file_path = os.path.join(TARGET_DIR, file_name)
        
        print(f"Downloading: {file_name}...")
        try:
            response = requests.get(file_url, stream=True, timeout=30)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"Successfully saved {file_name}")
            elif response.status_code == 404:
                # Some recent months might be stored in a different current-year directory profile
                print(f"File not found at standard archive URL (404): {file_name}")
            else:
                print(f"Failed to download {file_name}. Status code: {response.status_code}")
        except Exception as e:
            print(f"Error downloading {file_name}: {e}")

print(u"\nDownload loop complete! Files are saved in:", os.path.abspath(TARGET_DIR))
