"""SYNTHETIC DEMONSTRATION reference data.

!! NOT CLINICALLY VALIDATED. NOT A SOURCE OF DRUG INFORMATION. !!
These records exist only to exercise and test the rules engine. Names, interactions,
limits and warnings were written for software testing, were not verified against any
pharmaceutical reference, and MUST NOT be used for patient care. Every record is tagged
with the citation "SYNTHETIC-DEMO (unverified)". Real deployments must import a verified
dataset (see docs/REFERENCE_DATA.md) and have it approved by a second professional.
"""
from __future__ import annotations

from .refdata import Bundle

SYN = "Lokal.MD sample reference set (unverified)"


def demo_bundle_dict() -> dict:
    return {
        "meta": {
            "name": "Lokal.MD sample reference set",
            "version": "demo-1",
            "source_description": "Sample records (synthetic) bundled with Lokal.MD to exercise the rules engine. Not clinically validated.",
        },
        "classes": [
            {"key": "nsaid", "name": "NSAID", "aliases": ["nsaids", "non steroidal anti inflammatory"]},
            {"key": "penicillin", "name": "Penicillin", "aliases": ["penicillins", "pcn", "beta lactam penicillin"]},
            {"key": "cephalosporin", "name": "Cephalosporin", "aliases": ["cephalosporins"]},
            {"key": "sulfonamide", "name": "Sulfonamide", "aliases": ["sulfa", "sulfa drugs", "sulphonamide"]},
            {"key": "macrolide", "name": "Macrolide", "aliases": ["macrolides"]},
            {"key": "fluoroquinolone", "name": "Fluoroquinolone", "aliases": ["quinolone", "quinolones"]},
            {"key": "ace_inhibitor", "name": "ACE inhibitor", "aliases": ["ace inhibitors", "acei"]},
            {"key": "arb", "name": "Angiotensin receptor blocker", "aliases": ["arbs"]},
            {"key": "statin", "name": "Statin", "aliases": ["statins"]},
            {"key": "anticoagulant", "name": "Anticoagulant", "aliases": ["blood thinner", "blood thinners"]},
        ],
        "ingredients": [
            {"key": "paracetamol", "name": "Paracetamol", "aliases": ["acetaminophen", "apap"], "brands": ["Biogesic", "Calpol", "Tempra", "Tylenol"]},
            {"key": "ibuprofen", "name": "Ibuprofen", "classes": ["nsaid"], "brands": ["Advil", "Medicol", "Dolan"]},
            {"key": "mefenamic_acid", "name": "Mefenamic acid", "classes": ["nsaid"], "brands": ["Ponstan", "Dolfenal"]},
            {"key": "diclofenac", "name": "Diclofenac", "classes": ["nsaid"], "brands": ["Voltaren", "Cataflam"]},
            {"key": "aspirin", "name": "Aspirin", "classes": ["nsaid"], "aliases": ["acetylsalicylic acid", "asa"], "brands": ["Aspilets"]},
            {"key": "amoxicillin", "name": "Amoxicillin", "classes": ["penicillin"], "brands": ["Amoxil", "Moxylor"]},
            {"key": "ampicillin", "name": "Ampicillin", "classes": ["penicillin"]},
            {"key": "clavulanic_acid", "name": "Clavulanic acid", "aliases": ["clavulanate"]},
            {"key": "cefalexin", "name": "Cefalexin", "classes": ["cephalosporin"], "aliases": ["cephalexin"], "brands": ["Keflex"]},
            {"key": "cefuroxime", "name": "Cefuroxime", "classes": ["cephalosporin"], "brands": ["Zinnat"]},
            {"key": "sulfamethoxazole", "name": "Sulfamethoxazole", "classes": ["sulfonamide"]},
            {"key": "trimethoprim", "name": "Trimethoprim"},
            {"key": "azithromycin", "name": "Azithromycin", "classes": ["macrolide"], "brands": ["Zithromax"]},
            {"key": "clarithromycin", "name": "Clarithromycin", "classes": ["macrolide"], "brands": ["Klacid"]},
            {"key": "ciprofloxacin", "name": "Ciprofloxacin", "classes": ["fluoroquinolone"], "brands": ["Ciprobay"]},
            {"key": "metronidazole", "name": "Metronidazole", "brands": ["Flagyl"]},
            {"key": "warfarin", "name": "Warfarin", "classes": ["anticoagulant"], "brands": ["Coumadin"]},
            {"key": "metformin", "name": "Metformin", "brands": ["Glucophage"]},
            {"key": "losartan", "name": "Losartan", "classes": ["arb"], "brands": ["Cozaar"]},
            {"key": "captopril", "name": "Captopril", "classes": ["ace_inhibitor"]},
            {"key": "enalapril", "name": "Enalapril", "classes": ["ace_inhibitor"]},
            {"key": "amlodipine", "name": "Amlodipine", "brands": ["Norvasc"]},
            {"key": "simvastatin", "name": "Simvastatin", "classes": ["statin"], "brands": ["Zocor"]},
            {"key": "salbutamol", "name": "Salbutamol", "aliases": ["albuterol"], "brands": ["Ventolin"]},
            {"key": "cetirizine", "name": "Cetirizine", "brands": ["Zyrtec", "Allerkid"]},
            {"key": "omeprazole", "name": "Omeprazole", "brands": ["Losec"]},
        ],
        "products": [
            {"name": "Co-amoxiclav", "brands": ["Augmentin", "Amoxicillin-clavulanate", "Amox clav"], "ingredients": ["amoxicillin", "clavulanic_acid"]},
            {"name": "Co-trimoxazole", "brands": ["Bactrim", "Septrin", "Sulfamethoxazole-trimethoprim", "Cotrim"], "ingredients": ["sulfamethoxazole", "trimethoprim"]},
        ],
        "interactions": [
            {"a": "warfarin", "b": "class:nsaid", "severity": "major", "effect": "Increased bleeding risk when an anticoagulant is combined with an NSAID.", "management": "Clinician/pharmacist to review necessity and consider alternatives; monitoring plan per local protocol.", "source_citation": SYN},
            {"a": "warfarin", "b": "metronidazole", "severity": "major", "effect": "Possible increase in anticoagulant effect.", "management": "Review combination; consider additional monitoring per protocol.", "source_citation": SYN},
            {"a": "warfarin", "b": "sulfamethoxazole", "severity": "major", "effect": "Possible increase in anticoagulant effect.", "management": "Review combination; consider additional monitoring per protocol.", "source_citation": SYN},
            {"a": "class:ace_inhibitor", "b": "class:arb", "severity": "major", "effect": "Dual renin-angiotensin blockade: risk of hypotension, hyperkalaemia, renal effects.", "management": "Clinician to confirm intent; usually avoid combining.", "source_citation": SYN},
            {"a": "class:ace_inhibitor", "b": "class:nsaid", "severity": "moderate", "effect": "NSAIDs may reduce antihypertensive effect and increase renal risk.", "management": "Review necessity, hydration and renal function.", "source_citation": SYN},
            {"a": "class:arb", "b": "class:nsaid", "severity": "moderate", "effect": "NSAIDs may reduce antihypertensive effect and increase renal risk.", "management": "Review necessity, hydration and renal function.", "source_citation": SYN},
            {"a": "simvastatin", "b": "clarithromycin", "severity": "contraindicated", "effect": "Marked rise in statin exposure; risk of muscle toxicity.", "management": "Do not co-prescribe without specialist review; consider alternative antibiotic or temporary statin hold.", "source_citation": SYN},
            {"a": "simvastatin", "b": "amlodipine", "severity": "moderate", "effect": "Increased statin exposure; dose cap may apply.", "management": "Check statin dose against local reference.", "source_citation": SYN},
            {"a": "class:fluoroquinolone", "b": "class:nsaid", "severity": "moderate", "effect": "Possible increased CNS stimulation / seizure risk.", "management": "Review necessity and seizure history.", "source_citation": SYN},
            {"a": "class:nsaid", "b": "class:nsaid", "severity": "moderate", "effect": "Two NSAIDs together add GI/renal risk without added benefit.", "management": "Choose a single NSAID unless clearly intended.", "source_citation": SYN},
            {"a": "metformin", "b": "ciprofloxacin", "severity": "minor", "effect": "Possible blood-glucose disturbance.", "management": "Counsel patient; monitor glucose if symptomatic.", "source_citation": SYN},
        ],
        "contraindications": [
            {"subject": "class:nsaid", "condition_terms": ["peptic ulcer", "gastric ulcer", "gi bleeding", "gastrointestinal bleeding"], "severity": "major", "note": "NSAID with active/previous GI ulceration or bleeding.", "management": "Clinician review; consider non-NSAID analgesic.", "source_citation": SYN},
            {"subject": "class:nsaid", "condition_terms": ["kidney disease", "renal impairment", "renal failure", "ckd"], "severity": "major", "note": "NSAID in renal impairment.", "management": "Clinician review of renal function and alternatives.", "source_citation": SYN},
            {"subject": "class:nsaid", "condition_terms": ["pregnancy"], "severity": "major", "note": "NSAID use in pregnancy needs specific review.", "management": "Clinician review of gestational age and alternatives.", "source_citation": SYN},
            {"subject": "class:ace_inhibitor", "condition_terms": ["pregnancy"], "severity": "contraindicated", "note": "ACE inhibitor in pregnancy.", "management": "Do not prescribe; clinician to choose alternative.", "source_citation": SYN},
            {"subject": "class:arb", "condition_terms": ["pregnancy"], "severity": "contraindicated", "note": "ARB in pregnancy.", "management": "Do not prescribe; clinician to choose alternative.", "source_citation": SYN},
            {"subject": "warfarin", "condition_terms": ["pregnancy"], "severity": "contraindicated", "note": "Warfarin in pregnancy.", "management": "Specialist review required.", "source_citation": SYN},
            {"subject": "metformin", "condition_terms": ["kidney disease", "renal impairment", "renal failure", "ckd"], "severity": "major", "note": "Metformin with significant renal impairment.", "management": "Review renal function and dose.", "source_citation": SYN},
            {"subject": "aspirin", "condition_terms": ["asthma"], "severity": "moderate", "note": "Aspirin may worsen asthma in sensitive patients.", "management": "Review history of aspirin sensitivity.", "source_citation": SYN},
            {"subject": "ciprofloxacin", "condition_terms": ["pregnancy"], "severity": "major", "note": "Fluoroquinolone in pregnancy.", "management": "Clinician review; consider alternative.", "source_citation": SYN},
        ],
        "dose_limits": [
            {"ingredient": "paracetamol", "min_age_years": 12, "max_single": 1000, "max_daily": 4000, "unit": "mg", "note": "adult/adolescent limit for demo only", "source_citation": SYN},
            {"ingredient": "paracetamol", "min_age_years": 0, "max_age_years": 12, "max_single": 15, "max_daily": 60, "unit": "mg", "per_kg": True, "note": "paediatric per-kg limit for demo only", "source_citation": SYN},
            {"ingredient": "ibuprofen", "min_age_years": 12, "max_single": 800, "max_daily": 2400, "unit": "mg", "note": "demo only", "source_citation": SYN},
            {"ingredient": "ibuprofen", "min_age_years": 0.25, "max_age_years": 12, "max_single": 10, "max_daily": 40, "unit": "mg", "per_kg": True, "note": "demo only", "source_citation": SYN},
            {"ingredient": "metformin", "min_age_years": 18, "max_daily": 2550, "unit": "mg", "note": "demo only", "source_citation": SYN},
            {"ingredient": "amoxicillin", "min_age_years": 12, "max_single": 1000, "max_daily": 3000, "unit": "mg", "note": "demo only", "source_citation": SYN},
        ],
        "age_warnings": [
            {"subject": "aspirin", "max_age_years": 16, "severity": "major", "message": "Aspirin in children/adolescents: specific warning applies.", "management": "Clinician to confirm indication and consider alternatives.", "source_citation": SYN},
            {"subject": "ciprofloxacin", "max_age_years": 18, "severity": "moderate", "message": "Fluoroquinolone in patients under 18: restricted use.", "management": "Confirm indication; check local guideline.", "source_citation": SYN},
            {"subject": "sulfamethoxazole", "max_age_years": 0.1667, "severity": "major", "message": "Sulfonamide combination in very young infants.", "management": "Clinician review before use.", "source_citation": SYN},
            {"subject": "simvastatin", "max_age_years": 10, "severity": "moderate", "message": "Statin in young children: unusual; confirm indication.", "management": "Clinician review.", "source_citation": SYN},
            {"subject": "metformin", "min_age_years": 75, "severity": "minor", "message": "Older age: review renal function before dose decisions.", "management": "Check renal function.", "source_citation": SYN},
        ],
        "allergy_cross": [
            {"allergen": "class:penicillin", "drug": "class:cephalosporin", "severity": "moderate", "note": "Possible cross-reactivity between penicillin and cephalosporin allergy.", "source_citation": SYN},
            {"allergen": "class:sulfonamide", "drug": "sulfamethoxazole", "severity": "major", "note": "Sulfonamide allergy and a sulfonamide antibacterial.", "source_citation": SYN},
        ],
    }


def demo_bundle() -> Bundle:
    return Bundle.model_validate(demo_bundle_dict())
