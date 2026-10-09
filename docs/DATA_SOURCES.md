# Data sources and licences

RHU Scribe does **not** ship third-party medication data in the repository. `scripts/build_reference/` downloads the
public sources below and builds an import bundle on your machine; you then import it as "awaiting review".
None of it is clinically validated until a qualified person approves it (see `REFERENCE_DATA.md`).

## What each source provides

| Need | Source | Licence / terms | Commercial use |
|---|---|---|---|
| Ingredient names, combination-product aliases | DOH **Philippine National Formulary – Essential Medicines List**, Vol. I, 8th ed. (2019), as of 2 Nov 2022. PDF: https://www.philhealth.gov.ph/partners/providers/pdf/PNF-EML_11022022.pdf | Government publication; no reuse terms were stated in the file | Not confirmed – ask DOH Pharmaceutical Division |
| Drug–drug interactions (severity level only) | **DDInter 2.0**, Xiong G. et al., *Nucleic Acids Res.* 2022 – https://ddinter2.scbdd.com/download/ (8 ATC-group CSV files: A, B, D, H, L, P, R, V) | **CC BY-NC-SA 4.0** (site "Terms and conditions" → *Data licensing*) | **No – non-commercial, share-alike.** Obtain the authors' written permission or replace it with a licensed source before commercial deployment |
| Contraindications, paediatric age statements | **openFDA drug labels** (US FDA labelling, `api.fda.gov/drug/label`) – https://open.fda.gov/ | openFDA terms (public data, no warranty). Labels follow US approvals | Generally yes – confirm against the openFDA terms |
| Name spelling variants (paracetamol/acetaminophen, adrenaline/epinephrine, …) | Hand-written INN/USAN equivalence list in `build_bundle.py` / `fetch_openfda.py` | Facts (same molecule) | Yes |

## Known gaps (no open source was found)
* **Dose limits** – none imported. The app reports "no dose limit in reference data" instead of passing the dose.
* **Allergy class cross-reactivity and drug classes** – none imported (class-level interaction/allergy rules therefore do not fire). Direct allergen = ordered ingredient still works.
* **Philippine brand names** – the FDA Philippines portal offers lookup only, no bulk file. Unknown brand names are reported as unknown, never guessed.
* **Interaction mechanism / management text** – the DDInter downloads contain a severity level only; each rule says so and points to a pharmacist/reference.
* DDInter's bulk files do not include "C", "G", "J", "M", "N" or "S" ATC groups as separate files, but pairs involving those drugs appear when the other drug is in an included group (e.g. warfarin + ibuprofen). Coverage is therefore incomplete; "no interaction found" never means "none exists".
* `Unknown`-level DDInter pairs are not imported.

## Quality warnings
* Contraindication and age rows are **extracted automatically from label sentences** (keyword matching). Each row keeps the original sentence and label `set_id` so a pharmacist can verify it, but some will be out of context (for example an age limit that applies to one indication only).
* PNF text extraction is heuristic; unparsed entries are listed in the `review` section of the extractor output.

## Rebuilding
```
python scripts/build_reference/extract_pnf.py  pnf.pdf  pnf.json
python scripts/build_reference/fetch_openfda.py pnf.json fda_cache      # internet; ~1 request per ingredient
# download the 8 DDInter CSVs into ddinter/ (see table above)
python scripts/build_reference/build_bundle.py --pnf pnf.json --ddinter ddinter --fda fda_cache --out bundle.json [--scope pnf]
python scripts/import_reference.py bundle.json --activate              # activates for demonstration mode only
```
The bundle is a derivative of CC BY-NC-SA data: do not redistribute it outside the licence terms.
