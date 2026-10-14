import os
from pathlib import Path

# ===== CONFIG =====
BASE_DIR = Path("Exam paper clear")
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

# 6 grades x 4 subjects = 24 folders
GRADES = ["P1", "P2", "P3", "P4", "P5", "P6"]
SUBJECTS = ["Chi", "English", "Maths", "GS"]

def create_folders():
    # Base folders
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    created = []
    for grade in GRADES:
        for subject in SUBJECTS:
            folder = OUTPUT_DIR / f"{grade}_{subject}"
            folder.mkdir(parents=True, exist_ok=True)
            created.append(folder)

    # unknown folder for unclassified papers
    unknown = OUTPUT_DIR / "unknown"
    unknown.mkdir(parents=True, exist_ok=True)
    created.append(unknown)

    return created

if __name__ == "__main__":
    folders = create_folders()
    print(f"✅ Setup complete!\n")
    print(f"📥 Input  folder: {INPUT_DIR.resolve()}")
    print(f"📤 Output folder: {OUTPUT_DIR.resolve()}\n")
    print(f"Created {len(folders)} output folders:")
    for f in folders:
        print(f"  📁 {f}")