import requests
from bs4 import BeautifulSoup
import pandas as pd
import logging

BASE_YEAR = 2017

# Modify this to return less information while running (e.g., level=logging.DEBUG)
logging.basicConfig(level=logging.INFO)

datatypes = ['demographics', 'dietary', 'examination', 'laboratory', 'questionnaire']
# document links all have this base, used to fetch information below
linkbase = 'https://wwwn.cdc.gov'
#datatypes = ['questionnaire']

# Define description dataframe
descHeader = ["Label", "Plain Description", "Target"]
descDf = pd.DataFrame(columns=descHeader)
descDf.index.name = "Variable"

# Define mapping dataframe
mapDf = pd.DataFrame()
mapDf.index.name = "Variable"

# Files to Skip
lst = ("DR1IFF", "DR2IFF", "DSII", "AUXAR", "PAXHR", "PAXMIN", 'DRXFCD', 'DSBI', 'DSPI')
# Flag to grab SEQN variable only once
SEQNflag = True


def strip(s):
    return s.strip().replace('\r', '').replace('\n', '').replace('\t', '')

def grab_description(var, df):
    info = var.find_all('dd')
    name = strip(info[0].text)
    Label = strip(info[1].text)
    Plain_Description = strip(info[2].text)
    if len(info) == 4:
        Target = strip(info[3].text)
    elif len(info) == 5:
        Target = strip(info[4].text)
    else:
        Label = None
        Plain_Description = strip(info[1].text)
        Target = strip(info[2].text)
    df.loc[name] = {descHeader[0]: Label, descHeader[1]: Plain_Description, descHeader[2]: Target}
    #print({'Label': Label, 'Plain Description': Plain_Description, "Target": Target})


def grab_mapping(var, df):

    name = var.find('h3')["id"]
    if name == "SEQN":
        SEQNflag = False
    table = var.find("table")
    if table:
        rows = table.find_all('tr')

        # Create lists to store data
        for row in rows[1:]:
            cols = row.find_all(['td'])[:2]
            code = strip(cols[0].text)
            if code.isdigit() or code == ".":
                codeDesc = strip(cols[1].text)
                df.loc[name, code] = codeDesc
            else:
                return
                    

def grab_info(url):
    global descDf, mapDf, SEQNcount
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    vars = soup.find_all("div", class_="pagebreak")
    for var in vars:
        name = var.find('h3')["id"]
        if name == "SEQN" and not SEQNflag:
            break

        if not name.endswith("LC") and name != "SAMPLEID":
            grab_description(var, descDf)
            grab_mapping(var, mapDf)
                


for datatype in datatypes:
    logging.info(f'Now scraping definitions for {datatype} files')

    url = f'https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component={datatype}&CycleBeginYear={BASE_YEAR}'
    response = requests.get(url)

    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find('table')

    rows = table.find_all('tr')

    # Go row by row and save data
    for row in rows[1:]:
        col = row.find_all(['td'])[1]
        name = col.find('a').text
        if not name.startswith(lst):
            filelink = linkbase + col.find('a')["href"]
            grab_info(filelink)
    
# Sort mapping columns from smallest to largest
temp = mapDf.pop(".")
mapDf.columns = [int(col) for col in mapDf.columns]
mapDf = mapDf.sort_index(axis=1)
mapDf["."] = temp
    
# Save files
descDf.to_csv('descriptions.csv')
mapDf.to_csv('mappings.csv')
        



'''
# Clean up data
# Files to Skip
lst = ["DR1IFF", "DR2IFF", "DSII", "AUXAR", "PAXHR", "PAXMIN", 'DRXFCD', 'DSBI', 'DSPI']

# Remove unwanted variables
for l in lst:
    df = df[~df["Data File Name"].str.startswith(l)]   
df = df[~df["Variable Name"].str.endswith("LC")]
df = df[~(df["Variable Name"] == "SAMPLEID")]


# Sort alphabetically
df_sorted = df.sort_index(axis=1)

# Save file
df.to_csv("NHANES_Dictionary.csv")
'''