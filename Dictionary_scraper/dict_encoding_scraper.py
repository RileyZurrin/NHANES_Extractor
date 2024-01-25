import requests
from bs4 import BeautifulSoup
import pandas as pd
import logging
import os

# Change base year, if desired
BASE_YEAR = 2017

# Modify this to return less information while running (e.g., level=logging.DEBUG)
logging.basicConfig(level=logging.INFO)

datatypes = ['demographics', 'dietary', 'examination', 'laboratory', 'questionnaire']
linkbase = 'https://wwwn.cdc.gov'

# Define descriptions dataframe
header = ["DataType", "Label", "Plain Description", "Target"]
descDf = pd.DataFrame(columns=header)
descDf.index.name = "Variable"

# Define encoding dataframe
encDf = pd.DataFrame(columns=["Encoding"])
encDf.index.name = "Variable"

def file_filter(name):
    # Files to Skip
    skip_list = ("DR1IFF", "DR2IFF", "DSII", "AUXAR", "PAXHR", "PAXMIN", 'DRXFCD', 'DSBI', 'DSPI', 'DS1IDS','DS2IDS','DSQIDS','AUXTYM','AUXWBR','RXQ_RX')
    return not name.startswith(skip_list)

# count variables skipped
LC_count = 0
AUX_count = 0
def var_filter(name):
    global LC_count, AUX_count
    if name == "SEQN" and not SEQN_flag:
            return False
    if name.endswith("LC"):
        LC_count += 1
        return False
    lst = ("WBX", "TYX")
    if name.startswith(lst):
        AUX_count += 1
        return False
    if name == "SAMPLEID":
        return False
    return True

def strip(s):
    return s.strip().replace('\r', '').replace('\n', '').replace('\t', '')

def grab_description(var, df, datatype):
    info = var.find_all('dd')
    name = strip(info[0].text)
    Label = strip(info[1].text)
    Plain_Description = strip(info[2].text)
    numinfo = len(info) 
    if numinfo >= 4:
        Target = strip(info[numinfo - 1].text)
    else:
        Label = None
        Plain_Description = strip(info[1].text)
        Target = strip(info[2].text)
    df.loc[name] = {header[0]: datatype, header[1]: Label, header[2]: Plain_Description, header[3]: Target}

def grab_encoding(var, df):
    m = {}
    name = var.find('h3')["id"]
    global SEQN_flag
    if name == "SEQN":
        SEQN_flag = False
    table = var.find("table")
    if table:
        rows = table.find_all('tr')
        for row in rows[1:]:
            cols = row.find_all(['td'])[:2]
            code = strip(cols[0].text)
            if code.isdigit() or code == ".":
                codeDesc = strip(cols[1].text)
                if code.isdigit():
                    m[int(code)] = codeDesc
                else:
                    m[code] = codeDesc
        df.loc[name] = {"Encoding": m}
        
                    
def grab_info(url, datatype):
    global descDf, encDf, SEQN_flag
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    vars = soup.find_all("div", class_="pagebreak")
    if len(vars) > 0 and vars[0].find('h3')["id"] == "SEQN":
        for var in vars:
            name = var.find('h3')["id"]
            if var_filter(name):
                grab_description(var, descDf, datatype)
                grab_encoding(var, encDf)
    else:
        logging.info(f'{os.path.basename(url).split(".")[0]} file was skipped because it is not based on individual participants')
        return

for datatype in datatypes:
    logging.info(f'Now scraping definitions and encodings for {datatype} files')
    url = f'https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component={datatype}&CycleBeginYear={BASE_YEAR}'
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find('table')
    rows = table.find_all('tr')

    # Flags to grab SEQN variable only once per datatype
    SEQN_flag = True

    # Go row by row and save data
    for row in rows[1:]:
        col = row.find_all(['td'])[1]
        name = col.find('a').text
        if file_filter(name):
            filelink = linkbase + col.find('a')["href"]
            grab_info(filelink, datatype)
            
# Make a folder for the data
folder_name = f'NHANES_{BASE_YEAR}-{BASE_YEAR + 1}'
os.makedirs(folder_name, exist_ok=True)

# Save files
descDf.to_csv(folder_name + '/descriptions.csv')
encDf.to_csv(folder_name + '/encodings.csv')

# count comment codes skipped skipped
logging.info(f'{LC_count} variables skipped because they are comment codes')
logging.info(f'{AUX_count} variables skipped because they are large, unhelpful sensor data')
