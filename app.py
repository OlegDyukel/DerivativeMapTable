import datetime

from flask import Flask, render_template, request, url_for
from functions import get_data, get_table, send_message, make_html_text


app = Flask(__name__)

@app.route("/", methods = ["GET"])
def index():
    dict_table = get_table(get_data())
    # In: d_table["BR"]["2020 Dec"]
    # Out:    {'cell': {'cell_OI': '0', 'cell_name': 'BR 2020 Dec', 'cell_type': 0},
    # Out:     'instruments': {'futures': [], 'options': []}}
    return render_template("table.html",
                           dict_table=dict_table,
                           time_upd=datetime.datetime.now())

if __name__ == "__main__":
    app.run()


# разделить инструменты на исполняющиеся в пром и вк
# links of card: https://www.moex.com/ru/contract.aspx?code=RI130000BG0E
# links of desk: https://www.moex.com/ru/derivatives/optionsdesk.aspx?code=RTS-9.20
