"""Stage 2: read raw BEA xlsx workbooks into clean, labeled pandas objects.

Responsibilities
- Locate the header rows (code row + description row) without hard-coded offsets.
- Return a MakeTable (industries x commodities) and a UseTable split into its
  intermediate block, final-demand block, and value-added block, each with
  BEA codes as index/columns and descriptions carried alongside.
- Preserve the special commodity rows/columns (scrap S00401, used goods S00402,
  noncomparable imports S00300, rest-of-world adjustment S00900) so that the
  square-table stage can decide how to treat them.

Not yet implemented.
"""
