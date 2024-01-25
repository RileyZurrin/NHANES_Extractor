import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import xport
import pandas as pd
from io import BytesIO
import os


def extract(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Find all links, then narrow down to XPT files
    links = soup.find_all('a', href=True)
    xpt_files = [link['href'] for link in links if link['href'].endswith(('.XPT'))]

    # Download and convert each file
    for xpt in xpt_files:
        if xpt.endswith("PSTPOL_H.XPT") or xpt.endswith("PCBPOL_H.XPT") or xpt.endswith("BFRPOL_H.XPT"):
            print(xpt)
            xpt_url = urljoin(url, xpt)
            xpt_df = pd.read_sas(xpt_url)
            if not xpt_df.columns[0] == "SEQN":
                print(xpt_df.columns[0])
            xpt_df.set_index(xpt_df.columns[0], inplace=True)

            
            filename = os.path.basename(xpt)

            # Save the DataFrame as CSV
            xpt_df.to_csv(filename.replace(".XPT", ".csv"), index=True)



extract("https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Laboratory&CycleBeginYear=2013")