"""
Builds a one-line-per-constraint-member audit table so the LHS of every
AEMO "Gas Zone Daily Offtake Limit" constraint can be manually checked
against the source PLEXOS_gas_constraints.csv, and against which of those
plants actually show up in Offtake.csv.

Output: analysis_outputs/constraint_lhs_audit.csv
Columns:
  Gas Zone Constraint   - the PLEXOS constraint (Child Object)
  PLEXOS Generator      - LHS member exactly as named in
                          PLEXOS_gas_constraints.csv (Parent Object)
  Coefficient           - Offtake Coefficient value (should be 1 everywhere;
                          flagged if not)
  Offtake.csv Station   - the name this script assumes is the same plant in
                          Offtake.csv (blank if none)
  Present in Offtake.csv - whether that station name actually occurs in
                          Offtake.csv
  Note                  - why a plant has no Offtake.csv match (candidate/
                          unbuilt new entrant vs. unexplained gap)
"""
import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))

# PLEXOS generator name (as in PLEXOS_gas_constraints.csv) -> Offtake.csv
# "Name". Anything not listed here is assumed to be a candidate/new-entrant
# placeholder (name contains "new CCGT"/"new OCGT") that was not built in
# this run, UNLESS flagged otherwise below.
PLEXOS_TO_OFFTAKE = {
    "Colongra": "Colongra",
    "Bairnsdale": "Bairnsdale",
    "Jeeralang A": "Jeeralang",
    "Jeeralang B": "Jeeralang",
    "Smithfield Energy Facility": "Smithfield",
    "Tallawarra": "Tallawarra",
    "Tallawarra B": "Tallawarra B",
    "Tamar Valley Combined Cycle": "Tamar Valley CCGT",
    "Tamar Valley Peaking": "Tamar Valley OCGT",
    "Valley Power": "Valley Power",
    "Hunter Power Station": "Hunter",
    "Laverton North": "Laverton North",
    "Newport": "Newport",
    "Somerton": "Somerton",
    "Bolivar Power Station": "Bolivar Power Station",
    "Dry Creek GT": "Dry Creek",
    "Mintaro GT": "Mintaro",
    "Osborne": "Osborne",
    "Townsville Power Station": "Townsville",
    "Barcaldine Power Station": "Barcaldine",
    "Braemar": "Braemar",
    "Braemar 2 Power Station": "Braemar 2",
    "Condamine A": "Condamine",
    "Darling Downs": "Darling Downs",
    "Lockyer Valley GT": "Lockyer Valley GT",
    "Oakey Power Station": "Oakey",
    "Roma": "Roma",
    "Swanbank E GT": "Swanbank E",
    "Ladbroke Grove": "Ladbroke Grove",
    "Mortlake": "Mortlake OCGT",
    "Barker Inlet Power Station": "Barker Inlet",
    "Hallett GT": "Hallett",
    "Pelican Point": "Pelican Point",
    "Quarantine": "Quarantine",
    "Torrens Island B": "Torrens Island",
    "Uranquinty": "Uranquinty",
    # Existing plants named in the LHS with no row in Offtake.csv at all -
    # flagged as "unexplained gap" below rather than "candidate/unbuilt".
    "Bell Bay Three": None,
    "Snapper": None,
}


def main():
    c = pd.read_csv(os.path.join(BASE, "PLEXOS_gas_constraints.csv"), encoding="utf-8-sig")
    lhs = c[c["Property"] == "Offtake Coefficient"][["Child Object", "Parent Object", "Value"]]
    lhs = lhs.rename(columns={
        "Child Object": "Gas Zone Constraint",
        "Parent Object": "PLEXOS Generator",
        "Value": "Coefficient",
    })

    offtake_names = set(pd.read_csv(os.path.join(BASE, "Offtake.csv"), usecols=["Name"])["Name"].str.strip().unique())

    def offtake_station(gen):
        if gen in PLEXOS_TO_OFFTAKE:
            return PLEXOS_TO_OFFTAKE[gen]
        return gen  # assume identical name unless overridden above

    lhs["Offtake.csv Station"] = lhs["PLEXOS Generator"].map(offtake_station)
    lhs["Present in Offtake.csv"] = lhs["Offtake.csv Station"].apply(
        lambda n: n in offtake_names if n else False
    )

    def note(row):
        if row["Present in Offtake.csv"]:
            return ""
        if row["PLEXOS Generator"] in PLEXOS_TO_OFFTAKE and PLEXOS_TO_OFFTAKE[row["PLEXOS Generator"]] is None:
            return "In LHS but no matching row in Offtake.csv - unexplained gap, please verify"
        if "new CCGT" in row["PLEXOS Generator"] or "new OCGT" in row["PLEXOS Generator"]:
            return "Candidate/new-entrant plant - not built in this scenario"
        return "No Offtake.csv match found under assumed name - please verify"

    lhs["Note"] = lhs.apply(note, axis=1)

    if not (pd.to_numeric(lhs["Coefficient"]) == 1).all():
        print("WARNING: non-1 coefficients found:")
        print(lhs[lhs["Coefficient"] != 1])

    lhs = lhs.sort_values(["Gas Zone Constraint", "PLEXOS Generator"])
    out_dir = os.path.join(BASE, "analysis_outputs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "constraint_lhs_audit.csv")
    lhs.to_csv(out_path, index=False)
    print(f"Wrote {len(lhs)} rows to {out_path}")
    print(lhs["Note"].value_counts())


if __name__ == "__main__":
    main()
