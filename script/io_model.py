# %% [markdown]
# # An input-output price model of the U.S. economy
#
# Builds an industry-by-industry input-output table from BEA's make and use
# tables, then passes a cost shock through it to the prices consumers pay.
#
#     M          make table: what each industry produces     industries x commodities
#     U, D       use table: what industries and final users buy
#     U_m, D_m   the imported part of U and D
#     Z, F       the same purchases, by supplying industry
#     y          industry output
#     A, B       domestic and imported inputs per dollar of output
#     v          value added per dollar of output
#     p          prices, 1 in the base year
#
# Dollars are millions. Rates and price changes are fractions.

# %% Setup

from pathlib import Path

import numpy as np
import pandas as pd
import requests

YEAR = 2017
FOLDER = Path(__file__).parent if "__file__" in globals() else Path.cwd()
DATA = FOLDER / "data"
OUTPUT = FOLDER / "output"
BEA = "https://apps.bea.gov/industry/xls"

pd.set_option("display.width", 200, "display.float_format", "{:,.4f}".format)


def cached(url):
    """Download a file once; return its path."""
    path = DATA / url.split("/")[-1]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(url, timeout=120).content)
    return path


def read_table(url):
    """A BEA table as numbers labeled by BEA's codes, with the names of its row and column codes."""
    raw = pd.read_excel(cached(url), sheet_name=str(YEAR), header=None, dtype=str)
    top = raw.index[raw[0].str.strip().str.lower() == "code"][0]            # the row of column codes
    totals = {"Total Final Uses (GDP)": "T004", "Total Commodity Output": "T007", "Total Industry Output": "T008"}
    column_names = raw.loc[top - 1, 2:].str.strip()
    column_codes = raw.loc[top, 2:].str.strip().fillna(column_names.map(totals)).dropna()
    body = raw.loc[top + 1:].dropna(subset=[0, 1])                          # rows with a code and a name
    values = body[column_codes.index].astype(float).fillna(0.0)
    values.index, values.columns = body[0].str.strip().to_list(), column_codes.to_list()
    return values, dict(zip(values.index, body[1].str.strip())), dict(zip(values.columns, column_names[column_codes.index]))


def read_bridge(url):
    """BEA's PCE bridge: one row per consumer spending category and commodity."""
    raw = pd.read_excel(cached(url), sheet_name=str(YEAR), header=None, dtype=str)
    top = raw.index[raw[0].str.strip().str.lower() == "nipa line"][0]
    rows = raw.loc[top + 1:, :8].dropna(subset=[2])
    rows.columns = ["line", "category", "commodity", "commodity_name",
                    "producers", "transport", "wholesale", "retail", "purchasers"]
    dollars = ["producers", "transport", "wholesale", "retail", "purchasers"]
    rows[dollars] = rows[dollars].astype(float).fillna(0.0)
    rows["line"], rows["commodity"] = rows["line"].astype(int), rows["commodity"].str.strip()
    return rows.reset_index(drop=True)


# %% 1. The data

make, industry_name, _ = read_table(f"{BEA}/io-annual/IOMake_Before_Redefinitions_2017_Detail.xlsx")
use, commodity_name, final_use_name = read_table(f"{BEA}/io-annual/IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx")
imports, _, _ = read_table(f"{BEA}/io-annual/ImportMatrices_Before_Redefinitions_DET_2017.xlsx")
bridge = read_bridge(f"{BEA}/underlying-estimates/PCEBridge_2017_DET.xlsx")

industries = [c for c in make.index if not c.startswith("T0")]              # T0..: BEA's totals
commodities = [c for c in use.index if not c.startswith(("T0", "V0"))]      # V0..: value added
final_uses = [c for c in use.columns if c.startswith("F")]
buyers = [c for c in final_uses if c != "F05000"]                           # F05000: imports

M = make.loc[industries].reindex(columns=commodities, fill_value=0.0)
U = use.loc[commodities, industries]
D = use.loc[commodities, final_uses]
VA = use.loc[["V00100", "V00200", "V00300"], industries]                    # compensation, taxes, operating surplus
g = use.loc["T008", industries]                                             # BEA's industry output

U_m = imports.loc[commodities, industries]
D_m = imports.loc[commodities, buyers]

print(f"{len(industries)} industries, {len(commodities)} commodities, {len(final_uses)} final uses")
print(f"output {g.sum():,.0f}   value added {VA.sum().sum():,.0f}   imports {U_m.sum().sum() + D_m.sum().sum():,.0f}")

# %% 2. Commodities with no industry behind them
#
# An industry's output of these still counts toward its total, so its market
# shares in the next cell are scaled up by 1 / (share of output kept).

removed = ["S00401",    # scrap
           "S00402",    # used and secondhand goods
           "S00300",    # noncomparable imports
           "S00900"]    # rest-of-world adjustment

share_kept = 1 - M[removed].sum(axis=1) / g

M = M.drop(columns=removed)
U = U.drop(index=removed)
D = D.drop(index=removed)
U_m = U_m.drop(index=["S00401", "S00402", "S00900"])                        # noncomparable imports stay, as imports
D_m = D_m.drop(index=["S00401", "S00402", "S00900"])

print(share_kept.nsmallest(5).rename(index=industry_name).to_string())

# %% 3. Market shares
#
#     q = M' 1                  commodity output
#     N = M diag(q)^-1          industry i's share of commodity c

q = M.sum()
shares = M / q
N = shares.div(share_kept, axis=0)

print(shares.iloc[:4, :4])

# %% 4. The input-output table
#
#     Z = N U_d                 sales of industry i to industry j
#     F = N D_d                 sales of industry i to final users
#     y = Z 1 + F 1             industry output
#     A = Z diag(y)^-1          domestic inputs per dollar of output
#     B = U_m diag(y)^-1        imported inputs per dollar of output
#     v = value added / y

goods = U.index
total_imports = U_m.sum(axis=1) + D_m.sum(axis=1)

U_d = U - U_m.loc[goods]
D_d = D.copy()
D_d[buyers] -= D_m.loc[goods]
D_d["F05000"] += total_imports[goods]                                       # leaves duties and freight on imports

Z = N @ U_d
F = N @ D_d
y = Z.sum(axis=1) + F.sum(axis=1)

V = VA.copy()
V.loc["V00300"] = y - Z.sum() - U_m.sum() - V.loc["V00100"] - V.loc["V00200"]   # operating surplus balances

A = Z / y
B = U_m / y
v = V.sum() / y

assert np.allclose(A.sum() + B.sum() + v, 1)                                # costs per dollar of output
assert (y - g).abs().max() < 50                                             # BEA's output, to rounding

print(f"output {y.sum():,.0f} = domestic inputs {Z.sum().sum():,.0f} + imported inputs {U_m.sum().sum():,.0f}"
      f" + value added {V.sum().sum():,.0f}")

# %% 5. The shock
#
#     tau       new cost per dollar of an industry's output
#     tariff    rise in the price of an imported commodity
#     fixed     industries whose price change is given

tau = pd.Series(0.0, index=industries)
tariff = pd.Series(0.0, index=U_m.index)
fixed = {}

tariff["331110"] = 0.25                                     # 25% tariff on imported iron and steel

# tariff[:] = 0.10                                          # 10% tariff on all imports
# tau["211000"] = 50_000 / y["211000"]                      # $50 billion of cost on oil and gas extraction
# tau += 0.05 * q["324110"] * shares["324110"] / y          # 5% excise on refined petroleum
# tau += 0.01 * V.loc["V00100"] / y                         # compensation up 1% everywhere
# fixed["211000"] = 0.20                                    # the price of oil and gas up exactly 20%

# %% 6. The price model
#
#     p = A' p + B' p_m + v     price = cost per dollar of output; p = 1 in the base year
#     L = (I - A')^-1
#     p = L (v + tau + B' p_m)

L = pd.DataFrame(np.linalg.inv(np.eye(len(industries)) - A.T), index=industries, columns=industries)
assert np.allclose(L @ (v + B.sum()), 1)

p = L @ (v + tau + B.T @ (1 + tariff))

if fixed:                                                   # the cost on S that moves its prices to target:
    S = list(fixed)                                         #     L[S, S] tau_S = target - p_S
    tau[S] += np.linalg.solve(L.loc[S, S], 1 + pd.Series(fixed) - p[S])
    p = L @ (v + tau + B.T @ (1 + tariff))

dp = p - 1

print(dp.nlargest(10).rename(index=industry_name).map("{:.2%}".format).to_string())

# %% 7. Who pays
#
#     shock  = tau' y + tariff' imports
#     burden = dp' F + tariff' D_m          by final use; sums to the shock

shock = (tau * y).sum() + (tariff * total_imports).sum()

spending = F.sum().add(D_m.sum(), fill_value=0)[final_uses]
burden = (dp @ F).add(tariff @ D_m, fill_value=0)[final_uses]
assert np.isclose(burden.sum(), shock)

print(f"shock {shock:,.0f}")
print((burden / shock).nlargest(6).rename(index=final_use_name).map("{:.1%}".format).to_string())

# %% 8. Consumer prices
#
# The PCE bridge splits each spending category into commodities at producers'
# prices plus transport, wholesale and retail margins.

dp_c = shares.T @ dp                                        # domestic commodity prices

margin_industries = {
    "transport": ["481000", "482000", "483000", "484000", "486000"],
    "wholesale": ["423100", "423400", "423600", "423800", "423A00", "424200", "424400", "424700", "424A00", "425000"],
    "retail":    ["441000", "444000", "445000", "446000", "447000", "448000", "452000", "454000", "4B0000"],
}
margin = {name: np.average(dp_c[codes], weights=q[codes]) for name, codes in margin_industries.items()}

imported = D_m["F01000"]                                    # F01000: personal consumption
domestic = D_d["F01000"].reindex(imported.index, fill_value=0.0)
import_share = (imported / (imported + domestic)).fillna(0.0).clip(0, 1)

code = bridge["commodity"]
m = code.map(import_share).fillna(0.0)
bridge["dp"] = (1 - m) * code.map(dp_c).fillna(0.0) + m * code.map(tariff).fillna(0.0)
bridge["burden"] = (bridge["producers"] * bridge["dp"]
                    + bridge["transport"] * margin["transport"]
                    + bridge["wholesale"] * margin["wholesale"]
                    + bridge["retail"] * margin["retail"])

pce = bridge.groupby("line").agg(category=("category", "first"), spending=("purchasers", "sum"), burden=("burden", "sum"))
pce["price_change"] = (pce["burden"] / pce["spending"]).where(pce["spending"] != 0, 0.0)
pce["burden"] = pce["price_change"] * pce["spending"]

print(f"consumers bear {pce['burden'].sum():,.0f}, {pce['burden'].sum() / shock:.1%} of the shock")
print(pce.nlargest(10, "price_change")[["category", "price_change", "burden"]]
      .to_string(index=False, formatters={"price_change": "{:.2%}".format, "burden": "{:,.0f}".format}))

# %% 9. Results

industry_prices = pd.DataFrame({"code": industries, "description": [industry_name[c] for c in industries],
                                "price_change": dp.values})
commodity_prices = pd.DataFrame({"code": tariff.index, "description": [commodity_name[c] for c in tariff.index],
                                 "price_change": dp_c.reindex(tariff.index, fill_value=0.0).values,
                                 "import_price_change": tariff.values, "pce_import_share": import_share.values})
pce_prices = pd.DataFrame({"nipa_line": pce.index, "pce_category": pce["category"].values,
                           "price_change": pce["price_change"].values, "base_spending": pce["spending"].values,
                           "burden": pce["burden"].values})
burden_by_final_demand = pd.DataFrame({"code": final_uses, "description": [final_use_name[c] for c in final_uses],
                                       "base_spending": spending.values, "burden": burden.values})

OUTPUT.mkdir(parents=True, exist_ok=True)
for name in ["industry_prices", "commodity_prices", "pce_prices", "burden_by_final_demand"]:
    globals()[name].to_csv(OUTPUT / f"{name}.csv", index=False)
for name in ["Z", "F", "V", "A", "B"]:
    globals()[name].to_csv(OUTPUT / f"{name}.csv")
y.rename("y").to_csv(OUTPUT / "y.csv")

print(f"results in {OUTPUT}")

# %% 10. Appendix: BEA's published total requirements, (I - A)^-1
#
# BEA's table is after redefinitions, with imports combined and scrap kept.

make_a, _, _ = read_table(f"{BEA}/io-annual/IOMake_After_Redefinitions_2017_Detail.xlsx")
use_a, _, _ = read_table(f"{BEA}/io-annual/IOUse_After_Redefinitions_PRO_2017_Detail.xlsx")
published, _, _ = read_table(f"{BEA}/io-annual/IxI_TR_2017_PRO_DET.xlsx")

kept = [c for c in commodities if c not in ("S00402", "S00300", "S00900")]
M_a = make_a.loc[industries].reindex(columns=kept, fill_value=0.0)
g_a = use_a.loc["T008", industries]

N_a = (M_a / M_a.sum()).div(1 - make_a.loc[industries, "S00900"] / g_a, axis=0)
Z_a = N_a @ use_a.loc[kept, industries]
y_a = Z_a.sum(axis=1) + (N_a @ use_a.loc[kept, final_uses]).sum(axis=1)

ours = np.linalg.inv(np.eye(len(industries)) - (Z_a / y_a))
gap = np.abs(ours - published.loc[industries, industries])

print(f"largest difference from BEA's table: {gap.max().max():.1e}")
