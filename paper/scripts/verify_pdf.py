import sys
import unicodedata

import fitz

path = sys.argv[1] if len(sys.argv) > 1 else "../gridsense-ieee.pdf"
doc = fitz.open(path)

print(f"pages: {doc.page_count}")
print(f"metadata: {doc.metadata}")

bad_pages = []
for i, page in enumerate(doc):
    text = page.get_text()
    if "??" in text:
        bad_pages.append(i + 1)
print("pages containing literal '??':", bad_pages)

full_text = "".join(page.get_text() for page in doc)
non_ascii = {}
for ch in full_text:
    if ord(ch) > 127:
        key = (ch, unicodedata.name(ch, "UNKNOWN"), hex(ord(ch)))
        non_ascii[key] = non_ascii.get(key, 0) + 1

print("\nnon-ASCII character inventory:")
for (ch, name, code), count in sorted(non_ascii.items(), key=lambda kv: -kv[1]):
    print(f"  {code}  {name:35s}  x{count}")
