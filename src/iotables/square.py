"""Stage 3: transform make and use tables into a square industry-by-industry table.

Method (Chamberlain Economics methodology paper, Feb 2011; Eurostat "Model D",
fixed product sales structure; BEA calls it the industry-technology assumption):

    N = M * diag(q)^-1        market-share matrix, industries x commodities
    Z = N * U                 intermediate uses, industries x industries
    F = N * D                 final demand, industries x final-demand columns
    y = row sums of [Z | F]   total industry output
    value added: compensation and taxes taken from the use table; gross operating
    surplus is the balancing item so column totals equal y.

Adjustments before transforming: drop noncomparable imports and rest-of-world
adjustment rows; handle scrap and used/secondhand goods (proportional
redistribution per the methodology paper, or BEA's nonscrap-ratio adjustment).

Not yet implemented.
"""
