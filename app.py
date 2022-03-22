from datetime import datetime
import os
import requests
import pandas as pd
import time

from sqlalchemy import func
from flask import Flask, render_template, request, redirect, url_for
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
# from flask_wtf.csrf import CsrfProtect


from models import db, Underlying, Cell, Future, Option, FeedBack, AdminUser, Edition
from functions import get_data, get_table, get_colors, iss_urls, short_number, get_year_month, round_up_log
from config import Config


app = Flask(__name__)

app.config.from_object(Config)
db.init_app(app)
migrate = Migrate(app, db)
admin = Admin(app)


class MyUserView(ModelView):
    # Настройка общего списка
    column_exclude_list = ['password_hash']  # убрать из списка одно или несколько полей


admin.add_view(MyUserView(Underlying, db.session))
admin.add_view(MyUserView(Future, db.session))
admin.add_view(MyUserView(Option, db.session))
admin.add_view(MyUserView(Cell, db.session))
admin.add_view(MyUserView(Edition, db.session))


def update_futopt_tables(db_future_nrows, db_option_nrows):
    text_errors = []
    try:
        data = get_data()
    except:
        df_fut = pd.read_sql(db.session.query(Future).statement, db.session.bind)
        df_opt = pd.read_sql(db.session.query(Option).statement, db.session.bind)
    else:
        if 0.5*db_future_nrows < len(data["futures"]):
            # clear table with staled data
            db.session.query(Future).delete()

            # write fresh data
            for row in data["futures"].drop_duplicates().iterrows():
                future = Future(secid=row[1].SECID, shortname=row[1].SHORTNAME, lasttradedate=row[1].LASTTRADEDATE,
                                assetcode=row[1].ASSETCODE, prevopenposition=row[1].PREVOPENPOSITION,
                                prevsettleprice=row[1].PREVSETTLEPRICE, oi_rub=row[1].OI_RUB,
                                oi_percentage=row[1].OI_PERCENTAGE, lasttrademonth=row[1].LASTTRADEMONTH,
                                date_created=datetime.utcnow())
                db.session.add(future)

            try:
                editions = db.session.query(Edition).filter(Edition.table == "futures").first()
                editions.edition = data["future_edition"]
                editions.date_created = datetime.utcnow()
            except AttributeError:
                editions = Edition(table="futures", edition=data["future_edition"], date_created=datetime.utcnow())
                db.session.add(editions)

            db.session.commit()
        else:
            text_errors.append("a new data of futures has too little rows")


        if 0.5*db_option_nrows < len(data["options"]):
            # clear table with staled data
            db.session.query(Option).delete()

            # write fresh data
            for row in data["options"].drop_duplicates().iterrows():
                option = Option(secid=row[1].SECID, shortname=row[1].SHORTNAME, lasttradedate=row[1].LASTTRADEDATE,
                                assetcode=row[1].ASSETCODE, prevopenposition=row[1].PREVOPENPOSITION,
                                prevsettleprice=row[1].PREVSETTLEPRICE, oi_rub=row[1].OI_RUB,
                                oi_percentage=row[1].OI_PERCENTAGE, lasttrademonth=row[1].LASTTRADEMONTH,
                                underlying_future=row[1].UNDERLYING, date_created=datetime.utcnow())
                db.session.add(option)

            try:
                editions = db.session.query(Edition).filter(Edition.table == "options").first()
                editions.edition = data["option_edition"]
                editions.date_created = datetime.utcnow()
            except AttributeError:
                editions = Edition(table="options", edition=data["option_edition"], date_created=datetime.utcnow())
                db.session.add(editions)

            db.session.commit()
        else:
            text_errors.append("a new data of options has too little rows")

        df_fut = pd.read_sql(db.session.query(Future).statement, db.session.bind)
        df_opt = pd.read_sql(db.session.query(Option).statement, db.session.bind)
    return [df_fut, df_opt]


def update_underlying(df_fut):
    text_errors = []
    df_undrl = pd.read_sql(db.session.query(Underlying).statement, db.session.bind).set_index('underlying')
    new_set = set(df_fut['assetcode']).difference(set(df_undrl.index))

    if new_set:
        id = int(df_undrl['id'].max())
        for i in new_set:
            id += 1
            db_undrl = Underlying(id=id, underlying=i, name='', section_id=0, section='Новые',
                                  quote='', exp_clearing='', exp_type='', web_page='',
                                  date_created=datetime.utcnow())
            db.session.add(db_undrl)

        db.session.commit()

    df_undrl = pd.read_sql(db.session.query(Underlying).statement, db.session.bind).set_index('underlying')

    return df_undrl


def update_matrix(df_fut, df_opt, df_undrl):
    # combining tables fut and opt
    df_fut['type'] = 'F'
    df_opt['type'] = 'O'
    df_futopt_grouped = pd.concat([df_fut, df_opt]).groupby(["lasttrademonth", "assetcode"])

    # cell - max OI_RUB for coloring the cell
    cell_max_OI_rub = df_futopt_grouped['oi_rub'].sum().max()
    d_colors = get_colors()
    n_colors = len(d_colors)

    # cleaning cells table
    db.session.query(Cell).delete()

    # filling cells
    for name, group in df_futopt_grouped:
        cell_OI_rub = group['oi_rub'].sum()
        cell_type = set(group['type'].unique())
        db_cell = Cell(underlying=name[1], year_month=name[0],
                       color=d_colors[round_up_log(cell_OI_rub, cell_max_OI_rub, n_colors)],
                       label=" ".join(sorted([e for e in cell_type])),
                       date_created=datetime.utcnow())
        db.session.add(db_cell)

    db.session.commit()
    return 'd'


def update_matrix_reserved(df_fut, df_opt, df_undrl):
    # initializing table
    columns_fut = ["secid", "shortname", "lasttradedate", "prevopenposition", "oi_rub", "oi_percentage"]
    columns_opt = ["secid", "shortname", "lasttradedate", "prevopenposition", "oi_rub", "oi_percentage",
                   "underlying_future"]

    # cell - max OI_RUB for coloring the cell
    df_futopt = pd.concat([df_fut, df_opt])

    cell_max_OI_rub = pd.concat([df_fut[["lasttrademonth", "assetcode", "oi_rub"]],
                                 df_opt[["lasttrademonth", "assetcode", "oi_rub"]]]) \
        .groupby(["lasttrademonth", "assetcode"]).sum().max().values[0]

    d_colors = get_colors()
    n_colors = len(d_colors)

    # getting columns
    dates_lst = set(df_fut["lasttrademonth"]).union(set(df_opt["lasttrademonth"]))

    # cleaning cells table
    db.session.query(Cell).delete()

    # filling cells
    # db.session.query(Cell).delete()
    for row in df_fut["assetcode"].unique():
        for col in dates_lst:
            cell_OI = 0
            cell_type = set()
            cell_OI_rub = 0


            for i in df_fut[(df_fut["assetcode"] == row) & (df_fut["lasttrademonth"] == col)][columns_fut].values:
                cell_OI += i[3]
                cell_OI_rub += i[4]
                cell_type.add("F")

            for i in df_opt[(df_opt["assetcode"] == row) & (df_opt["lasttrademonth"] == col)][columns_opt].values:
                cell_OI += i[3]
                cell_OI_rub += i[4]
                cell_type.add("O")

            if len(cell_type) > 0:
                temp_df = df_undrl[df_undrl.index == row]
                if not temp_df.empty:
                    db_cell = Cell(underlying=row, year_month=col,
                                    color=d_colors[round_up_log(cell_OI_rub, cell_max_OI_rub, n_colors)],
                                    label=" ".join(sorted([e for e in cell_type])),
                                    # name=temp_df['name'].values[0],
                                    # section=temp_df['section'].values[0],
                                    # quote=temp_df['quote'].values[0],
                                    # web_page=temp_df['web_page'].values[0],
                                    date_created=datetime.utcnow())
                else:
                    db_cell = Cell(underlying=row, year_month=col,
                                    color=d_colors[round_up_log(cell_OI_rub, cell_max_OI_rub, n_colors)],
                                    label=" ".join(sorted([e for e in cell_type])),
                                    date_created=datetime.utcnow())

                db.session.add(db_cell)

    db.session.commit()
    return 'd'


def get_dictionary(df_cell, df_fut, df_opt):

    # getting columns and rows
    underlying_lst = df_cell['underlying'].unique()
    date_lst = df_cell['year_month'].unique()

    # initializing table
    d = {}
    columns_fut = ["secid", "shortname", "lasttradedate", "prevopenposition", "oi_rub", "oi_percentage"]
    columns_opt = ["secid", "shortname", "lasttradedate", "prevopenposition", "oi_rub", "oi_percentage", "underlying_future"]

    # filling cells
    for row in underlying_lst:
        d[row] = {}
        for col in date_lst:
            d[row][col] = {"cell_name": '',
                                "cell_params": {},
                                "futures": [],
                                "options": []}

    dict_cell = df_cell.set_index(['underlying', 'year_month']).to_dict(orient='index')

    for key, value in dict_cell.items():
        lst_fut = df_fut[(df_fut["assetcode"] == key[0]) & (df_fut["lasttrademonth"] == key[1])][columns_fut].to_dict(orient='records')
        lst_opt = df_opt[(df_opt["assetcode"] == key[0]) & (df_opt["lasttrademonth"] == key[1])][columns_opt].to_dict(orient='records')

        d[key[0]][key[1]] = {
                "cell_name": "{}{}".format(key[0], key[1].replace(" ", "")),
                "cell_params": value,
                "futures": lst_fut,
                "options": lst_opt}
    return d


@app.route("/", methods=["GET"])
def index():
    df_fut = pd.DataFrame()
    df_opt = pd.DataFrame()
    df_undrl = pd.DataFrame()

    # db.session.query(Future).delete()
    # db.session.query(Cell).delete()
    # грубо проверяем что в БД консистентные данные. проверка по кол-ву записей (50 записей для фьючей)
    db_future_nrows = db.session.query(Future).count()
    db_option_nrows = db.session.query(Option).count()
    if db_future_nrows < 100 or db_option_nrows < 50:
        df_fut, df_opt = update_futopt_tables(db_future_nrows, db_option_nrows)
        df_undrl = update_underlying(df_fut)
        dict_cell = update_matrix(df_fut, df_opt, df_undrl)

    # во-вторых проверяем совпадение даты сегодня и даты обновления таблицы
    try:
        db_future_date = db.session.query(func.max(Future.date_created)).first()[0].strftime("%Y-%m-%d")
        db_option_date = db.session.query(func.max(Option.date_created)).first()[0].strftime("%Y-%m-%d")
    except AttributeError:
        db_future_date = "1999-09-19"
        db_option_date = "1999-09-19"
    current_date = datetime.utcnow().strftime("%Y-%m-%d")

    if db_future_date != current_date or db_option_date != current_date:
        # далее проверяем версионность данных - в выходные даты могут не совпадать, но в источнике также не обновл
        db_future_edition = db.session.query(Edition).filter(Edition.table == "futures").first().edition
        db_option_edition = db.session.query(Edition).filter(Edition.table == "options").first().edition
        iss_future_edition = requests.get(iss_urls()["query_futures_edition"]).json()["dataversion"]["data"][0][0]
        iss_option_edition = requests.get(iss_urls()["query_options_edition"]).json()["dataversion"]["data"][0][0]
        if db_future_edition != iss_future_edition or db_option_edition != iss_option_edition:
            df_fut, df_opt = update_futopt_tables(db_future_nrows, db_option_nrows)
            df_undrl = update_underlying(df_fut)
            dict_cell = update_matrix(df_fut, df_opt, df_undrl)


    if df_fut.empty:
        df_fut = pd.read_sql(db.session.query(Future).statement, db.session.bind)
    if df_opt.empty:
        df_opt = pd.read_sql(db.session.query(Option).statement, db.session.bind)
    if df_undrl.empty:
        df_undrl = pd.read_sql(db.session.query(Underlying).statement, db.session.bind).set_index('underlying')

    df_cell = pd.read_sql(db.session.query(Cell).statement, db.session.bind)


    dict_undrl = df_undrl.to_dict(orient='index')

    dict_section = df_undrl[['section', 'section_id']] \
        .sort_values(by=['section_id']).to_dict()['section']
    dict_section_converted = {}

    for value in dict_section.values():
        dict_section_converted[value] = []

    index = df_fut[['assetcode', 'oi_rub']].groupby('assetcode').sum()\
            .sort_values('oi_rub', ascending=False).index

    for undrl in index:
        if dict_section[undrl] in dict_section_converted:
            dict_section_converted[dict_section[undrl]].append(undrl)
        else:
            dict_section_converted[dict_section[undrl]] = [undrl]

    dict_matrix = get_dictionary(df_cell, df_fut, df_opt)

    lst_months = []
    for dt in pd.period_range(start=df_fut["lasttradedate"].min(),
                              end=df_fut["lasttradedate"].max(),
                              freq='M'):
        lst_months.append(get_year_month(dt))

    return render_template("table.html",
                           colors=get_colors(),
                           dict_section=dict_section_converted,
                           dict_undrl=dict_undrl,
                           lst_months=lst_months,
                           dict_matrix=dict_matrix,
                           time_upd=current_date)

if __name__ == "__main__":
    app.run()
