# Medication reference data

Tala ships **only synthetic demonstration data** (`rhuscribe/safety/demo_data.py`). Every record is
tagged `SYNTHETIC-DEMO (unverified)`. It exists to test the rules engine and **must not be used for patient care**.

## Going live (clinical mode)
1. A pharmacist/administrator **imports** a verified dataset (Settings → Medication reference). Every record needs a `source_citation`.
2. A *different* qualified person (pharmacist or clinician) **reviews and approves** it, recording what was checked.
3. An administrator **activates** it and switches the app to **clinical mode**. Until then every screen and PDF is marked as demonstration.
   If the active dataset is not approved, clinical mode fails closed (no checks run, approval is blocked).

## JSON bundle format (see the example download in the app)
Sections: `meta`, `classes`, `ingredients` (with `aliases`, `brands`, `classes`), `products` (combination products),
`interactions` (`a`,`b` = ingredient key or `class:<key>`), `contraindications` (`condition_terms`), `dose_limits`
(`max_single`/`max_daily`, `unit` mg|g|mcg, `per_kg`, age band), `age_warnings`, `allergy_cross`.
Severities: `contraindicated`, `major`, `moderate`, `minor`.

## CSV import
One file per section named after it (`interactions.csv`, `ingredients.csv`, …). Required columns are listed in
`rhuscribe/safety/refdata.py` (`CSV_SECTIONS`). List cells use `|` as separator.

## What the engine does (and does not) do
Deterministic matching only: name/brand→ingredient, duplicates, interactions (ingredient or class level), allergy and
same-class/cross-reactivity, age bands, contraindications by recorded conditions/pregnancy, dose limits (single/daily,
per-kg, mg conversion from tablet strength or mg/mL), order completeness. Results are classified as *detected concern*,
*potential concern*, *no rules triggered*, *incomplete check*, *unknown/unavailable* or *cannot check*.
"No rules triggered" is never presented as "safe". Unknown drug names are never auto-corrected (suggestions only).
