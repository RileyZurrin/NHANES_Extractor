import pandas as pd

# Merge duplicate columns. 
def combine_dupes(df: pd.DataFrame):

    # Begin by enumerating duplicates:
    col = df.columns.to_list()

    # Initialize a dictionary to store indices
    index_dict = {}

    # Iterate over the array and store indices for each unique value
    for index, value in enumerate(col):
        if value not in index_dict:
            index_dict[value] = [index]
        else:
            index_dict[value].append(index)

    # Filter out values with only one occurrence (non-duplicates)
    duplicates_dict = {key: value for key, value in index_dict.items() if len(value) > 1}

    # Merge duplicates and enumerate columns that need to be dropped
    col2drop = []
    for _, value in duplicates_dict.items():
        for col in value[1:]:
            df.iloc[:, value[0]] = df.iloc[:, value[0]].combine_first(df.iloc[:, col])
            col2drop.append(col)

    # Drop all but first duplicate columns
    df = df.iloc[:, [j for j, c in enumerate(df.columns) if j not in col2drop]]

    return df