# Summary
The Data_scraper/scraper.py file in this repo grabs all NHANES data for a given year inputted by the user (e.g., 2017) from the [CDC Website](https://wwwn.cdc.gov/nchs/nhanes/default.aspx) and organizes it into a categorized, appropriately named folder. For example, the folder titled Data_scraper/NHANES_2017-2018 was generated using this script. 

Can also scrape variable dictionary and encodings for a given year using Dictionary_scraper/dict_encoding_scraper.py file.

# Use
[NHANES data](https://wwwn.cdc.gov/nchs/nhanes/default.aspx) is partitioned into two year ranges (e.g., 2015-2016). To use for a given partition, change the "BASE_YEAR" line in Data_scraper/scraper.py to the first of the two years ("2015" for 2015-2016).

The 2017-2018 is available for use on [Kaggle](https://www.kaggle.com/datasets/rileyzurrin/national-health-and-nutrition-exam-survey-2017-2018/data), with links to variable descriptions and encodings.

Can also scrape variable dictionary and encodings by inputting "BASE_YEAR" into Dictionary_scraper/dict_encoding_scraper.py file.
