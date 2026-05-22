from pathlib import Path
import csv
import cv2

ROOT = Path(r"C:\Users\HP\Desktop\【大二下】【计算机视觉】\project\PVZAgent\zombieImages")
OUTPUT = Path("asset_manifest.csv")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

rows = []

for path in ROOT.rglob("*"):
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        continue

    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)

    if img is None:
        width = height = channels = ""
        has_alpha = False
    else:
        height, width = img.shape[:2]
        channels = img.shape[2] if len(img.shape) == 3 else 1
        has_alpha = channels == 4

    rows.append({
        "relative_path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "file_name": path.name,
        "folder": str(path.parent.relative_to(ROOT)).replace("\\", "/"),
        "width": width,
        "height": height,
        "channels": channels,
        "has_alpha": has_alpha,
    })

rows.sort(key=lambda r: r["relative_path"])

with OUTPUT.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "relative_path",
            "file_name",
            "folder",
            "width",
            "height",
            "channels",
            "has_alpha",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Done. Found {len(rows)} images.")
print(f"Saved to {OUTPUT.resolve()}")
