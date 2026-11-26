"""Synthesizes the demo documents. Prompts live in demos/synth_prompts/*.md (committed).
Text docs -> mistral -> PDF (fpdf2). The spares catalogue CSV is generated deterministically (seeded)."""
import csv, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fpdf import FPDF
from forgeai import llm

HERE = Path(__file__).resolve().parent
PLAN = {"hr": ["hr_leave_policy", "hr_remote_work", "hr_expenses"],
        "spares": ["sp_supplier_a", "sp_supplier_b", "sp_procurement_policy"]}

def to_latin1(t):
    for a, b in {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u2022": "-", "\u20ac": "EUR ", "\u2026": "..."}.items():
        t = t.replace(a, b)
    return t.encode("latin-1", "replace").decode("latin-1")

def pdf(text, path):
    p = FPDF(); p.add_page(); p.set_auto_page_break(True, 15); p.set_font("Helvetica", size=11)
    for line in to_latin1(text).splitlines():
        p.multi_cell(0, 6, line.replace("**", "").replace("#", "").strip() or " ", new_x="LMARGIN", new_y="NEXT")
    p.output(str(path))

def catalogue(path):
    rng = random.Random(42)
    items = [("Fuel injector nozzle", "Main engine"), ("Piston ring set", "Main engine"), ("Cylinder liner", "Main engine"),
             ("Turbocharger cartridge", "Main engine"), ("Centrifugal pump impeller", "Pumps"), ("Mechanical seal", "Pumps"),
             ("Bilge pump motor", "Pumps"), ("Oil filter element", "Filtration"), ("Fuel filter element", "Filtration"),
             ("Air compressor valve kit", "Compressors"), ("Navigation light LED unit", "Electrical"), ("Alternator brush set", "Electrical"),
             ("Hydraulic hose 2m", "Deck"), ("Mooring winch brake pad", "Deck"), ("Lifeboat release hook", "Safety"),
             ("Fire detector head", "Safety"), ("Boiler gauge glass", "Boilers"), ("Steering gear seal kit", "Steering")]
    sup = ["Nordhaven Marine Supply AS", "Pacific Engine Parts Ltd"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["part_number", "description", "system", "supplier", "unit_price_usd", "stock_on_hand", "lead_time_days", "critical_spare"])
        for i, (d, s) in enumerate(items):
            w.writerow([f"MP-{1000 + i * 7}", d, s, rng.choice(sup), round(rng.uniform(18, 4200), 2), rng.randint(0, 40), rng.choice([5, 7, 14, 21, 35, 60]), rng.choice(["yes", "no"])])

if __name__ == "__main__":
    for demo, names in PLAN.items():
        for n in names:
            out = HERE / demo / "docs" / f"{n.split('_', 1)[1]}.pdf"
            if out.exists():
                continue
            prompt = (HERE / "synth_prompts" / f"{n}.md").read_text(encoding="utf-8")
            text = llm.chat([{"role": "user", "content": prompt}], temperature=0.7, num_predict=1100)
            pdf(text, out); print("wrote", out, len(text), "chars", flush=True)
    catalogue(HERE / "spares" / "docs" / "spares_catalogue.csv"); print("wrote catalogue")
