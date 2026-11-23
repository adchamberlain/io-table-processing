# The model as one script

`io_model.py` builds an industry-by-industry input-output table of the U.S.
economy from BEA's make and use tables and passes a change in costs through it
to the prices consumers pay. This folder is self-contained.

## Set up, once

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

Open `io_model.py` in an editor that understands `# %%` cells (Cursor, VS Code,
PyCharm, Spyder), choose the `.venv` interpreter, and run the cells in order.
Or run it all at once: `python io_model.py`.

The first run downloads about 20 MB of BEA workbooks into `data/`. Results are
written as CSV files to `output/`.

## The cells

| Cell | What it does |
| --- | --- |
| Setup | Libraries, and three helpers that download and read BEA's spreadsheets |
| 1 | The data: make table, use table, import matrix, PCE bridge |
| 2 | Commodities with no industry behind them |
| 3 | Market shares |
| 4 | The input-output table |
| 5 | The cost change |
| 6 | The price model |
| 7 | Who pays, by final use |
| 8 | Consumer prices |
| 9 | Results |
| 10 | Appendix: BEA's published total requirements |

## Cost changes

Cell 5 sets the change on the model's inputs. `c` is new cost per dollar of an
industry's output, `import_price` the rise in the price of an imported
commodity, and `fixed` a given price change for an industry.

```python
import_price["331110"] = 0.25                           # 25% tariff on imported iron and steel
import_price[:] = 0.10                                  # all import prices up 10%
c["211000"] = 50_000 / y["211000"]                      # $50 billion of cost on oil and gas extraction
c += 0.05 * q["324110"] * shares["324110"] / y          # 5% excise on refined petroleum
c += 0.01 * V.loc["V00100"] / y                         # compensation up 1% everywhere
fixed["211000"] = 0.20                                  # the price of oil and gas up exactly 20%
```

The model does not ask where a cost comes from: a tax, a tariff, a world price
and a wage increase all enter the same way. Industry and commodity codes are
BEA's; `industry_name` and `commodity_name` give their descriptions.

## Reading the results

- Dollars are millions of 2017 dollars. A price change of 0.05 is 5 percent.
- Costs are passed forward in full and quantities are held fixed, so the
  results are a short-run upper bound.
- Domestic producers do not raise prices to match a tariff on competing
  imports. Use `fixed` on the domestic industry to assume that they do.
- A dozen cells of BEA's import matrix exceed the matching cell of the use
  table, nearly all for biological products (325414); they are used as
  published.
- Every commodity has one imported share in consumer purchases, the same in
  each spending category that buys it.
