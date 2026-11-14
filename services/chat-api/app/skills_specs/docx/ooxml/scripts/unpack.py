#!/usr/bin/env python3
"""Unpack and format XML contents of Office files (.docx, .pptx, .xlsx)"""

import random
import pathlib


def _safe_extract(zf, dest):
    """Zip-slip-safe extraction (QF-420).

    Extract every member only when its resolved path stays inside *dest*.
    Guards against absolute paths and ``../`` traversal entries. Works on
    Python 3.10+ without relying on the 3.12+ ``filter=`` argument.
    """
    dest = pathlib.Path(dest).resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if target != dest and dest not in target.parents:
            raise ValueError(f"Refusing zip-slip entry: {member.filename!r}")
        zf.extract(member, str(dest))
import sys
import defusedxml.minidom
import zipfile
from pathlib import Path

# Get command line arguments
assert len(sys.argv) == 3, "Usage: python unpack.py <office_file> <output_dir>"
input_file, output_dir = sys.argv[1], sys.argv[2]

# Extract and format
output_path = Path(output_dir)
output_path.mkdir(parents=True, exist_ok=True)
_safe_extract(zipfile.ZipFile(input_file), output_path)

# Pretty print all XML files
xml_files = list(output_path.rglob("*.xml")) + list(output_path.rglob("*.rels"))
for xml_file in xml_files:
    content = xml_file.read_text(encoding="utf-8")
    dom = defusedxml.minidom.parseString(content)
    xml_file.write_bytes(dom.toprettyxml(indent="  ", encoding="ascii"))

# For .docx files, suggest an RSID for tracked changes
if input_file.endswith(".docx"):
    suggested_rsid = "".join(random.choices("0123456789ABCDEF", k=8))
    print(f"Suggested RSID for edit session: {suggested_rsid}")
