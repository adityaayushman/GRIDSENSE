import sys

import fitz

path = sys.argv[1] if len(sys.argv) > 1 else "../gridsense-ieee.pdf"
pages = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else None

doc = fitz.open(path)
indices = range(doc.page_count) if pages is None else [p - 1 for p in pages]
for i in indices:
    page = doc[i]
    pix = page.get_pixmap(dpi=200)
    out = f"../figures/_preview_p{i+1}.png"
    pix.save(out)
    print("wrote", out)
