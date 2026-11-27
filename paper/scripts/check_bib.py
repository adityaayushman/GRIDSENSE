import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "../gridsense-ieee.tex"
text = open(path, encoding="utf-8").read()
bibitems = re.findall(r"\\bibitem\{([a-zA-Z0-9_]+)\}", text)
cites = re.findall(r"\\cite\{([a-zA-Z0-9_, ]+)\}", text)
cite_keys = []
for c in cites:
    for k in c.split(","):
        k = k.strip()
        if k not in cite_keys:
            cite_keys.append(k)
print("bibitems order:", bibitems)
print("first-citation order:", cite_keys)
print("MATCH:", bibitems == cite_keys)
missing_bib = [k for k in cite_keys if k not in bibitems]
orphan_bib = [k for k in bibitems if k not in cite_keys]
print("cited but no bibitem:", missing_bib)
print("bibitem never cited:", orphan_bib)
