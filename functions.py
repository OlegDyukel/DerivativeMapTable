import requests
import pandas as pd
import numpy as np
import re




def get_updates():
    url = get_url() + "getupdates"
    r = requests.get(url)
    return r.json()


def get_message():
    data = get_updates()

    chat_id = data["result"][-1]["message"]["chat"]["id"]
    message_text = data["result"][-1]["message"]["text"]

    message = {"chat_id": chat_id, "message_text": message_text}

    return message


def send_message(chat_id, text="hold on please..."):
    url = get_url() + "sendmessage?chat_id={}&parse_mode=HTML&text={}".format(chat_id, text)
    requests.get(url)


def get_option_series_name(s):
    st = re.sub("[CP]A[\d\.\-]+$", "", s)
    return st


def get_option_underlying(option_name):
    st = re.split("M\d{6}", option_name)
    return st[0]


def get_year_month(date):
    return date.strftime("%Y %b")


def short_number(number):
    try:
        d = {0: "", 1: "K", 2: "M", 3: "B"}
        power = (len(str(int(number))) - 1)//3
        devisor = 10**(3*power)
        if number/devisor < 10 and number >= 10:
            modificated_number = round(number/devisor, 1)
        else:
            modificated_number = int(round(number/devisor, 0))
        return "{}{}".format(modificated_number, d[power])
    except ValueError:
        return "0"


def get_data(exp_date=None):
    columns_input = ["SECID", "SHORTNAME", "LASTTRADEDATE", "ASSETCODE", "PREVOPENPOSITION", "PREVSETTLEPRICE",
                     "MINSTEP", "STEPPRICE"]

    # futures
    url_fut = "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json?iss.only=securities&securities.columns={}".format(
        ','.join(columns_input))
    r_fut = requests.get(url_fut)
    data_fut = r_fut.json()["securities"]["data"]
    columns_fut = r_fut.json()["securities"]["columns"]
    df_fut = pd.DataFrame(data_fut, columns=columns_fut)

    # options
    url_opt = "https://iss.moex.com/iss/engines/futures/markets/options/securities.json?iss.only=securities&securities.columns={}".format(
        ",".join(columns_input))
    r_opt = requests.get(url_opt)
    data_opt = r_opt.json()["securities"]["data"]
    columns_opt = r_opt.json()["securities"]["columns"]
    df_opt_raw = pd.DataFrame(data_opt, columns=columns_opt)

    # deleting NaN data
    df_fut = df_fut[-df_fut["PREVOPENPOSITION"].isnull()]
    df_opt_raw = df_opt_raw[-df_opt_raw["PREVOPENPOSITION"].isnull()]

    # getting underlying
    df_opt_raw["UNDERLYING"] = df_opt_raw["SHORTNAME"].apply(get_option_underlying)

    # getting short option names = cutting strikes and types
    df_opt_raw["SHORTNAME"] = df_opt_raw["SHORTNAME"].apply(get_option_series_name)

    # getting STEPPRICE param for options from futures
    df_opt_raw = df_opt_raw.merge(df_fut[["SHORTNAME", "STEPPRICE"]],
                                  how="left", left_on="UNDERLYING", right_on="SHORTNAME", suffixes=["", "_y"])

    # calc OI_RUB
    df_fut["OI_RUB"] = df_fut["PREVOPENPOSITION"] * df_fut["PREVSETTLEPRICE"] * df_fut["STEPPRICE"] / df_fut["MINSTEP"]
    df_opt_raw["OI_RUB"] = df_opt_raw["PREVOPENPOSITION"] * df_opt_raw["PREVSETTLEPRICE"] * df_opt_raw["STEPPRICE"] / \
                           df_opt_raw["MINSTEP"]

    # filtering, sorting and grouping
    if exp_date:
        df_fut = df_fut[df_fut["LASTTRADEDATE"] == exp_date].sort_values(by=["PREVOPENPOSITION"], ascending=False)
        df_opt = df_opt_raw[df_opt_raw["LASTTRADEDATE"] == exp_date].groupby(
            ["SHORTNAME", "LASTTRADEDATE", "ASSETCODE", "UNDERLYING"]).agg(
            {"PREVOPENPOSITION": "sum", "OI_RUB": "sum", "SECID": "max",
             "PREVSETTLEPRICE": "mean"}).reset_index().sort_values(by=["OI_RUB"], ascending=False)
    else:
        df_fut = df_fut.sort_values(by=["PREVOPENPOSITION"], ascending=False)
        df_opt = df_opt_raw.groupby(["SHORTNAME", "LASTTRADEDATE", "ASSETCODE", "UNDERLYING"]).agg(
            {"PREVOPENPOSITION": "sum", "OI_RUB": "sum", "SECID": "max",
             "PREVSETTLEPRICE": "mean"}).reset_index().sort_values(by=["OI_RUB"], ascending=False)

    # OI_PERCENTAGE(sum_undrl = 100%)
    df_fut["OI_PERCENTAGE"] = 100 * df_fut[["PREVOPENPOSITION"]] / df_fut[["ASSETCODE", "PREVOPENPOSITION"]].groupby(
        "ASSETCODE").transform("sum")
    df_opt["OI_PERCENTAGE"] = 100 * df_opt[["PREVOPENPOSITION"]] / df_opt[["ASSETCODE", "PREVOPENPOSITION"]].groupby(
        "ASSETCODE").transform("sum")

    # transforming date type
    df_fut["LASTTRADEDATE"] = pd.to_datetime(df_fut["LASTTRADEDATE"])
    df_opt["LASTTRADEDATE"] = pd.to_datetime(df_opt["LASTTRADEDATE"])

    df_fut["LASTTRADEMONTH"] = df_fut["LASTTRADEDATE"].apply(get_year_month)
    df_opt["LASTTRADEMONTH"] = df_opt["LASTTRADEDATE"].apply(get_year_month)

    columns_output_fut = ["SECID", "SHORTNAME", "LASTTRADEDATE", "ASSETCODE", "PREVOPENPOSITION",
                          "PREVSETTLEPRICE", "OI_RUB", "OI_PERCENTAGE", "LASTTRADEMONTH"]
    columns_output_opt = ["SECID", "SHORTNAME", "LASTTRADEDATE", "ASSETCODE", "PREVOPENPOSITION",
                          "PREVSETTLEPRICE", "OI_RUB", "OI_PERCENTAGE", "LASTTRADEMONTH", "UNDERLYING"]

    return {"futures": df_fut[columns_output_fut], "options": df_opt[columns_output_opt]}


def get_table(data_FO_dict):
    df_fut = data_FO_dict["futures"]
    df_opt = data_FO_dict["options"]

    # getting columns
    dates_lst = []
    for dt in pd.period_range(start=df_fut["LASTTRADEDATE"].min(),
                              end=df_fut["LASTTRADEDATE"].max(),
                              freq='M'):
        dates_lst.append(dt.strftime("%Y %b"))

    # initializing table
    d = {}
    columns_fut = ["SECID", "SHORTNAME", "LASTTRADEDATE", "PREVOPENPOSITION", "OI_RUB", "OI_PERCENTAGE"]
    columns_opt = ["SECID", "SHORTNAME", "LASTTRADEDATE", "PREVOPENPOSITION", "OI_RUB", "OI_PERCENTAGE", "UNDERLYING"]

    # filling cells
    for row in df_fut["ASSETCODE"].unique():
        d[row] = {}
        for col in dates_lst:
            d[row][col] = {
                "cell": {"cell_name": "{}{}".format(row, col.replace(" ", "")), "cell_type": '', "cell_OI": 0},
                "instruments": {"futures": [], "options": []}}
            cell_OI = 0
            cell_type = set()

            for i in df_fut[(df_fut["ASSETCODE"] == row) & (df_fut["LASTTRADEMONTH"] == col)][columns_fut].values:
                cell_OI += i[3]
                cell_type.add("F")
                d[row][col]["instruments"]["futures"].append({"short_ticker": i[0],
                                                              "ticker": i[1],
                                                              "exp_date": i[2],
                                                              "OI": i[3],
                                                              "OI_RUB": i[4],
                                                              "OI_PERCENTAGE": i[5]})

            for i in df_opt[(df_opt["ASSETCODE"] == row) & (df_opt["LASTTRADEMONTH"] == col)][columns_opt].values:
                cell_OI += i[3]
                cell_type.add("O")
                d[row][col]["instruments"]["options"].append({"short_ticker": i[0],
                                                              "ticker": i[1],
                                                              "exp_date": i[2],
                                                              "OI": i[3],
                                                              "OI_RUB": i[4],
                                                              "OI_PERCENTAGE": i[5],
                                                              "UNDERLYING": i[6]})

            if len(cell_type) > 0:
                d[row][col]["cell"]["cell_type"] = "+".join(sorted([e for e in cell_type]))
                d[row][col]["cell"]["cell_OI"] = short_number(cell_OI)

            # In: d_table["BR"]["2020 Dec"]
            # Out:    {'cell': {'cell_OI': '0', 'cell_name': 'BR 2020 Dec', 'cell_type': 0},
            # Out:     'instruments': {'futures': [], 'options': []}}

    return d


def make_html_text(current_date, type_instr, df):
    d_type = {"futures": "фьючерсов", "options": "опционов"}
    html_text = "<pre> Сегодня ({}) последний день торгов для {} {}: </pre>\n"\
        .format(current_date, df.shape[0], d_type[type_instr])
    for index, row in df.iterrows():
        html_text += "{} ~ открыто {:,} контр. \n".format(str(row["SHORTNAME"]),
                                                              int(row["PREVOPENPOSITION"]))
    return html_text