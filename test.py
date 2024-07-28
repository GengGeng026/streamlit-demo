from taipy.gui import Markdown
import pandas as pd

def get_data(path_to_csv: str):
    # pandas.read_csv() returns a pd.DataFrame
    dataset = pd.read_csv("Users/mac/Desktop/Streamlit/data/habits.csv")
    dataset["Date"] = pd.to_datetime(dataset["Date"])
    return dataset

# Read the dataframe
path_to_csv = "data/habits.csv"
dataset = get_data("Users/mac/Desktop/Streamlit/data/habits.csv")

# Initial value
n_week = 10

# Select the week based on the slider value
dataset_week = dataset[dataset["Date"].dt.isocalendar().week == n_week]

def on_slider(state):
    state.dataset_week = dataset[dataset["Date"].dt.isocalendar().week == state.n_week]


data_viz = Markdown("pages/data_viz/data_viz.md")