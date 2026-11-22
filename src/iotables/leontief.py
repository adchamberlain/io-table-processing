"""Stage 4: Leontief price model on the square table, for climate-policy analysis.

Baseline (Tax Foundation WP6, eqs. 10-11; Fullerton 1995 / Metcalf 1999):
    A  = Z * diag(y)^-1            technical coefficients (column shares)
    v  = value added / y
    p  = (I - A')^-1 v             equals a vector of ones in the base year

Policy (WP6 eqs. 13-15): T = diag(1 + t), t_i = policy cost borne by industry i
as a share of its intermediate sales;  p_hat = (I - A' T)^-1 v.
Commodity prices via a make-based transformation matrix; consumer categories via
the BEA PCE bridge.

Not yet implemented.
"""
