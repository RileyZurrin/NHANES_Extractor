import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE_YEAR = 2017
datatypes = ['demographics', 'dietary', 'examination', 'laboratory', 'questionnaire']
df = pd.DataFrame()
for datatype in datatypes:

    url = f"https://wwwn.cdc.gov/nchs/nhanes/search/variablelist.aspx?Component={datatype}&Cycle={BASE_YEAR}-{BASE_YEAR+1}"
    response = requests.get(url)

    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find('table')

    rows = table.find_all('tr')

    headercols = rows[0].find_all(['th'])
    headercols = [headercol.text.strip() for headercol in headercols]

    # Create lists to store data
    data = []
    for row in rows[1:]:
        cols = row.find_all(['td'])
        cols = [col.text.strip() for col in cols]
        data.append(cols)

    # Create a Pandas DataFrame
    dfadd = pd.DataFrame(data, columns=headercols)
    df = pd.concat([df,dfadd], ignore_index=True)

# Clean up data
# Files to Skip
lst = ["DR1IFF", "DR2IFF", "DSII", "AUXAR", "PAXHR", "PAXMIN", 'DRXFCD', 'DSBI', 'DSPI']

# Remove unwanted variables
for l in lst:
    df = df[~df["Data File Name"].str.startswith(l)]   
df = df[~df["Variable Name"].str.endswith("LC")]
df = df[~(df["Variable Name"] == "SAMPLEID")]

# Keep only useful columns for dictionary
del df["Data File Name"]
del df["Data File Description"]
del df["Begin Year"]
del df["EndYear"]
del df["Use Constraints"]

# Move component
cols = df.columns.tolist()
cols = [cols[0], cols[2],cols[1]]
df = df[cols]

# Set index as variable and sort alphabetically
df.set_index("Variable Name", inplace=True)
df_sorted = df.sort_index(axis=1)

# Save file
df.to_csv("NHANES_Dictionary.csv")