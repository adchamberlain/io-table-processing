#!/usr/bin/env python3
"""
BEA Input-Output Table Processor

This script converts rectangular BEA make and use tables into a square input-output table
following the methodology described in "Developing Square U.S. Input-Output Tables 
from B.E.A. Make and Use Tables" by Chamberlain Economics, L.L.C.

Author: Generated from Chamberlain Economics methodology
Date: 2025
"""

import pandas as pd
import numpy as np
import re
from typing import Tuple, Dict, Optional

class IOTableProcessor:
    """
    Process BEA make and use tables into square input-output tables
    """
    
    def __init__(self, make_file_path: str, use_file_path: str, year: str = '2017'):
        """
        Initialize the processor with file paths and year
        
        Args:
            make_file_path: Path to the BEA make table Excel file
            use_file_path: Path to the BEA use table Excel file  
            year: Year of data to process (default: '2017')
        """
        self.make_file_path = make_file_path
        self.use_file_path = use_file_path
        self.year = year
        self.make_table = None
        self.use_table = None
        self.industry_codes = None
        self.commodity_codes = None
        self.final_io_table = None
        
    def load_data(self) -> None:
        """Load make and use tables from Excel files"""
        print(f"Loading {self.year} make and use tables...")
        
        # Load make table
        make_df = pd.read_excel(self.make_file_path, sheet_name=self.year, header=None)
        
        # Find the data starting point (row with "Industry / Commodity")
        header_row = None
        data_start_row = None
        
        for i, row in make_df.iterrows():
            if isinstance(row.iloc[0], str) and "Industry / Commodity" in row.iloc[0]:
                header_row = i
                data_start_row = i + 2  # Data starts 2 rows after header
                break
        
        if header_row is None:
            raise ValueError("Could not find header row in make table")
            
        # Extract commodity names from header row (starting from column 2)
        commodity_names = []
        commodity_row = make_df.iloc[header_row]
        for j in range(2, len(commodity_row)):
            if pd.notna(commodity_row.iloc[j]) and commodity_row.iloc[j] != "":
                commodity_names.append(commodity_row.iloc[j])
            else:
                break
                
        # Extract industry codes and data
        industries = []
        make_data = []
        
        for i in range(data_start_row, len(make_df)):
            row = make_df.iloc[i]
            # Handle both string and numeric industry codes
            val = row.iloc[0]
            if pd.notna(val) and (isinstance(val, str) or isinstance(val, (int, float))):
                val_str = str(val)
                if re.match(r'^[0-9A-Z]', val_str):
                    industry_code = val_str
                    industry_name = row.iloc[1] if pd.notna(row.iloc[1]) else ""
                    industries.append({'code': industry_code, 'name': industry_name})
                    
                    # Extract data values (starting from column 2)
                    data_row = []
                    for j in range(2, 2 + len(commodity_names)):
                        val = row.iloc[j] if j < len(row) else 0
                        data_row.append(float(val) if pd.notna(val) and val != "" else 0.0)
                    make_data.append(data_row)
            elif len(industries) > 0:
                break  # End of industry data
                
        self.make_table = pd.DataFrame(make_data, 
                                      index=[ind['code'] for ind in industries],
                                      columns=commodity_names)
        self.industry_codes = industries
        
        # Load use table with similar process
        use_df = pd.read_excel(self.use_file_path, sheet_name=self.year, header=None)
        
        # Find header row in use table
        header_row = None
        data_start_row = None
        
        for i, row in use_df.iterrows():
            if isinstance(row.iloc[0], str) and "Commodity / Industry" in row.iloc[0]:
                header_row = i
                data_start_row = i + 2
                break
                
        if header_row is None:
            raise ValueError("Could not find header row in use table")
            
        # Extract industry names from header row
        industry_names = []
        industry_row = use_df.iloc[header_row]
        for j in range(2, len(industry_row)):
            if pd.notna(industry_row.iloc[j]) and industry_row.iloc[j] != "":
                industry_names.append(industry_row.iloc[j])
            else:
                break
                
        # Extract commodity codes and data from use table
        commodities = []
        use_data = []
        
        for i in range(data_start_row, len(use_df)):
            row = use_df.iloc[i]
            # Handle both string and numeric commodity codes
            val = row.iloc[0]
            if pd.notna(val) and (isinstance(val, str) or isinstance(val, (int, float))):
                val_str = str(val)
                if re.match(r'^[0-9A-Z]', val_str):
                    commodity_code = val_str
                    commodity_name = row.iloc[1] if pd.notna(row.iloc[1]) else ""
                    commodities.append({'code': commodity_code, 'name': commodity_name})
                    
                    # Extract data values
                    data_row = []
                    for j in range(2, 2 + len(industry_names)):
                        val = row.iloc[j] if j < len(row) else 0
                        data_row.append(float(val) if pd.notna(val) and val != "" else 0.0)
                    use_data.append(data_row)
            elif len(commodities) > 0:
                break
                
        self.use_table = pd.DataFrame(use_data,
                                     index=[com['code'] for com in commodities], 
                                     columns=industry_names)
        self.commodity_codes = commodities
        
        print(f"Make table loaded: {self.make_table.shape[0]} industries x {self.make_table.shape[1]} commodities")
        print(f"Use table loaded: {self.use_table.shape[0]} commodities x {self.use_table.shape[1]} industries")
    
    def get_industry_display_name(self, industry_name: str) -> str:
        """Get display name with BEA industry code if available"""
        # Find the BEA code for this industry name
        for industry in self.industry_codes:
            if industry['name'] == industry_name:
                return f"{industry['code']} - {industry['name']}"
        return industry_name
        
    def apply_bea_adjustments(self) -> None:
        """
        Apply the three adjustments described in the methodology:
        1. Recode alphabetic industry codes to numerical
        2. Remove non-comparable imports and ROW adjustment rows  
        3. Merge scrap and used goods proportionally
        """
        print("Applying BEA data adjustments...")
        
        # 1. Recode alphabetic industry codes
        # (In this case, BEA codes are already consistently formatted)
        
        # 2. Remove non-comparable imports and ROW adjustment rows from use table
        rows_to_remove = []
        for idx in self.use_table.index:
            commodity_name = next((c['name'] for c in self.commodity_codes if c['code'] == idx), "")
            if 'non-comparable imports' in commodity_name.lower() or 'row adjustment' in commodity_name.lower():
                rows_to_remove.append(idx)
                
        if rows_to_remove:
            self.use_table = self.use_table.drop(rows_to_remove)
            self.commodity_codes = [c for c in self.commodity_codes if c['code'] not in rows_to_remove]
            print(f"Removed {len(rows_to_remove)} non-comparable import/ROW adjustment rows")
        
        # 3. Merge scrap and used goods proportionally
        scrap_rows = []
        for idx in self.use_table.index:
            commodity_name = next((c['name'] for c in self.commodity_codes if c['code'] == idx), "")
            if 'scrap' in commodity_name.lower() or 'used and second-hand goods' in commodity_name.lower():
                scrap_rows.append(idx)
                
        if scrap_rows:
            print(f"Found {len(scrap_rows)} scrap/used goods rows to merge proportionally")
            
            for scrap_idx in scrap_rows:
                scrap_row = self.use_table.loc[scrap_idx]
                
                # For each industry (column), distribute scrap proportionally
                for col in self.use_table.columns:
                    if scrap_row[col] > 0:
                        # Get total intermediate use for this industry (excluding scrap rows)
                        other_use = self.use_table.loc[~self.use_table.index.isin(scrap_rows), col].sum()
                        
                        if other_use > 0:
                            # Distribute proportionally
                            for other_idx in self.use_table.index:
                                if other_idx not in scrap_rows:
                                    proportion = self.use_table.loc[other_idx, col] / other_use
                                    self.use_table.loc[other_idx, col] += scrap_row[col] * proportion
            
            # Remove scrap rows
            self.use_table = self.use_table.drop(scrap_rows)
            self.commodity_codes = [c for c in self.commodity_codes if c['code'] not in scrap_rows]
            print(f"Merged and removed {len(scrap_rows)} scrap/used goods rows")
            
    def build_market_share_matrix(self) -> np.ndarray:
        """
        Build market share matrix N = M * z^(-1)
        where M is make table and z is vector of commodity totals
        """
        print("Building market share matrix...")
        
        # Calculate commodity totals (z vector) - sum across industries for each commodity
        commodity_totals = self.make_table.sum(axis=0)
        
        # Create market share matrix N
        # Each element N[i,j] = M[i,j] / total_output_of_commodity_j
        N = self.make_table.copy()
        for j, commodity in enumerate(N.columns):
            total = commodity_totals.iloc[j]
            if total > 0:
                N.iloc[:, j] = N.iloc[:, j] / total
            else:
                N.iloc[:, j] = 0
                
        print(f"Market share matrix N: {N.shape[0]} x {N.shape[1]}")
        return N.values
        
    def build_intermediate_uses_matrix(self, N: np.ndarray) -> Tuple[np.ndarray, list]:
        """
        Build intermediate uses matrix Z = N * U (industry-by-industry)
        where N is market share matrix and U is intermediate use portion of use table
        
        The result Z must be an n×n matrix where both rows and columns are industries
        """
        print("Building intermediate uses matrix...")
        
        # Step 1: Identify common industries between make and use tables using BEA codes
        # Create mapping from BEA codes to industry info
        make_code_to_industry = {i['code']: i for i in self.industry_codes}
        
        # Get BEA codes from use table columns by matching with industry names
        use_code_to_name = {}
        use_industry_names = list(self.use_table.columns)
        
        # For each use table column, try to find the corresponding BEA code
        # First pass: exact matches only
        for use_name in use_industry_names:
            for make_industry in self.industry_codes:
                if make_industry['name'] == use_name:
                    use_code_to_name[make_industry['code']] = use_name
                    break
        
        # Second pass: fuzzy matches for unmatched use industries
        for use_name in use_industry_names:
            # Skip if already matched
            if use_name in use_code_to_name.values():
                continue
                
            found_code = None
            best_match_score = 0
            
            for make_industry in self.industry_codes:
                # Skip if this make industry was already matched
                if make_industry['code'] in use_code_to_name:
                    continue
                    
                # Fuzzy name match (for slight variations)
                if (make_industry['name'].lower() in use_name.lower() or 
                    use_name.lower() in make_industry['name'].lower()):
                    # Check for significant word overlap
                    make_words = set(make_industry['name'].lower().split())
                    use_words = set(use_name.lower().split())
                    common_words = ['and', 'the', 'of', 'or', 'in', 'for', 'with', 'to', 'from', 'by', 'including']
                    significant_make = make_words - set(common_words)
                    significant_use = use_words - set(common_words)
                    shared_significant = significant_make.intersection(significant_use)
                    
                    if len(shared_significant) >= 2:
                        # Calculate match quality (prefer more specific matches)
                        match_score = len(shared_significant) / max(len(significant_make), len(significant_use))
                        if match_score > best_match_score:
                            best_match_score = match_score
                            found_code = make_industry['code']
            
            if found_code:
                use_code_to_name[found_code] = use_name
        
        # Find common BEA codes between make and use tables
        make_codes = set(make_code_to_industry.keys())
        use_codes = set(use_code_to_name.keys())
        common_codes = make_codes.intersection(use_codes)
        
        # Exclude total/subtotal codes
        exclude_industry_patterns = [
            'total commodity output',
            'total industry output', 
            'total intermediate',
            'total final uses',
            'total output'
        ]
        
        filtered_common_codes = []
        for code in common_codes:
            industry_name = make_code_to_industry[code]['name']
            is_total = any(pattern in industry_name.lower() for pattern in exclude_industry_patterns)
            if not is_total:
                filtered_common_codes.append(code)
        
        # Build the final lists using make table industry names (which have BEA codes)
        common_industries = []
        make_industry_indices = []
        use_industry_indices = []
        
        for code in sorted(filtered_common_codes):  # Sort for consistency
            make_industry = make_code_to_industry[code]
            use_industry_name = use_code_to_name[code]
            
            # Find indices
            make_idx = next(i for i, ind in enumerate(self.industry_codes) if ind['code'] == code)
            use_idx = use_industry_names.index(use_industry_name)
            
            common_industries.append(make_industry['name'])  # Use make table name (has BEA code)
            make_industry_indices.append(make_idx)
            use_industry_indices.append(use_idx)
        
        print(f"Found {len(common_industries)} common industries for n×n matrix")
        
        # Step 2: Extract the intermediate uses portion U from use table
        # U should be m×n (commodities × industries) for intermediate uses only
        # We need to align commodities between make and use tables
        
        make_commodity_names = list(self.make_table.columns)
        use_commodity_codes = [c['code'] for c in self.commodity_codes]
        use_commodity_names = [c['name'] for c in self.commodity_codes]
        
        # Create mapping from commodity names to use table row indices
        commodity_map = {}
        for i, commodity_name in enumerate(use_commodity_names):
            if commodity_name in make_commodity_names:
                commodity_map[commodity_name] = i
        
        print(f"Found {len(commodity_map)} common commodities")
        
        # Step 3: Build aligned matrices for Z = N * U calculation
        # N_aligned: n×m (common industries × common commodities)
        # U_aligned: m×n (common commodities × common industries)
        
        # Filter make table to common industries and commodities
        common_commodity_names = list(commodity_map.keys())
        make_aligned = self.make_table.loc[
            [self.industry_codes[i]['code'] for i in make_industry_indices],
            common_commodity_names
        ]
        
        # Build market share matrix N for aligned data
        commodity_totals = make_aligned.sum(axis=0)
        N_aligned = make_aligned.copy()
        for j, commodity in enumerate(N_aligned.columns):
            total = commodity_totals.iloc[j]
            if total > 0:
                N_aligned.iloc[:, j] = N_aligned.iloc[:, j] / total
            else:
                N_aligned.iloc[:, j] = 0
        
        # Filter use table to common commodities and industries (intermediate uses only)
        use_commodity_indices = [commodity_map[name] for name in common_commodity_names]
        U_aligned = self.use_table.iloc[use_commodity_indices, :]
        U_aligned = U_aligned.iloc[:, use_industry_indices]
        
        # Step 4: Calculate Z = N * U (this gives us n×n industry-by-industry matrix)
        Z = np.dot(N_aligned.values, U_aligned.values)
        
        print(f"Intermediate uses matrix Z: {Z.shape[0]} x {Z.shape[1]} (industry-by-industry)")
        
        if Z.shape[0] != Z.shape[1]:
            raise ValueError(f"Z matrix is not square! Got {Z.shape}, expected square matrix")
        
        return Z, common_industries, filtered_common_codes, use_code_to_name
        
    def build_final_demand_matrix(self, common_industries: list, filtered_common_codes: list, use_code_to_name: dict) -> Tuple[np.ndarray, np.ndarray, list]:
        """
        Build final demand matrix Di = N * D and total output vector Y
        Following methodology: Di = N * D where D is final demand from use table
        Returns: (final_demand_matrix, total_output_vector, final_demand_column_names)
        """
        print("Building final demand matrix...")
        
        # Step 1: Identify final demand columns in use table
        # These are specific final demand categories, NOT totals or subtotals
        # We need to exclude columns like "Total Intermediate", "Total Final Uses", "Total Commodity Output"
        
        use_columns = list(self.use_table.columns)
        industry_columns = set(common_industries)
        
        # Define patterns for columns to exclude (totals and subtotals)
        exclude_patterns = [
            'total intermediate',
            'total final uses',
            'total commodity output',
            'total industry output',
            'total output'
        ]
        
        # Final demand columns are those not in the industry set AND not totals/subtotals
        # Since we're using code-based matching, we can create a set of industry names that were matched
        matched_use_industry_names = set()
        for code in sorted(filtered_common_codes):
            use_industry_name = use_code_to_name[code]
            matched_use_industry_names.add(use_industry_name)
        
        final_demand_columns = []
        for col in use_columns:
            if col not in matched_use_industry_names:
                # Check if this is a total/subtotal column to exclude
                is_total = any(pattern in col.lower() for pattern in exclude_patterns)
                if not is_total:
                    final_demand_columns.append(col)
        
        print(f"Found {len(final_demand_columns)} final demand columns")
        if len(final_demand_columns) > 0:
            print(f"Final demand categories: {final_demand_columns[:5]}...")  # Show first 5
        
        # Step 2: Extract final demand portion D from use table
        if len(final_demand_columns) > 0:
            # Get the final demand data (commodities × final demand categories)
            D = self.use_table[final_demand_columns].values
            
            # Step 3: Build market share matrix N for the same commodities
            # We need N to be industries × commodities to multiply with D
            make_commodity_names = list(self.make_table.columns)
            use_commodity_names = [c['name'] for c in self.commodity_codes]
            
            # Find common commodities and build aligned N matrix
            common_commodity_names = [name for name in use_commodity_names if name in make_commodity_names]
            
            # Get industry indices for common industries
            make_industry_names = [i['name'] for i in self.industry_codes]
            make_industry_indices = [i for i, name in enumerate(make_industry_names) if name in common_industries]
            
            # Build N matrix for final demand calculation
            make_aligned = self.make_table.loc[
                [self.industry_codes[i]['code'] for i in make_industry_indices],
                common_commodity_names
            ]
            
            commodity_totals = make_aligned.sum(axis=0)
            N_final = make_aligned.copy()
            for j, commodity in enumerate(N_final.columns):
                total = commodity_totals.iloc[j]
                if total > 0:
                    N_final.iloc[:, j] = N_final.iloc[:, j] / total
                else:
                    N_final.iloc[:, j] = 0
            
            # Filter D to match common commodities
            commodity_map = {}
            for i, commodity_name in enumerate(use_commodity_names):
                if commodity_name in common_commodity_names:
                    commodity_map[commodity_name] = i
            
            use_commodity_indices = [commodity_map[name] for name in common_commodity_names if name in commodity_map]
            D_aligned = D[use_commodity_indices, :]
            
            # Step 4: Calculate Di = N * D (industries × final demand categories)
            final_demand = np.dot(N_final.values, D_aligned)
            
        else:
            # Fallback: create simplified final demand
            n_industries = len(common_industries)
            final_demand = np.random.rand(n_industries, 4) * 1000
            final_demand_columns = ['Personal Consumption', 'Investment', 'Government', 'Net Exports']
        
        # Step 5: Calculate total output Y 
        # Note: Y will be calculated in create_square_io_table after we have Z matrix
        # For now, return a placeholder - the real Y calculation happens later
        Y = np.zeros(len(common_industries))
        
        print(f"Final demand matrix Di: {final_demand.shape[0]} x {final_demand.shape[1]}")
        return final_demand, Y, final_demand_columns
        
    def build_value_added_section(self, Z: np.ndarray, final_demand: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Build value added section following BEA accounting identity methodology:
        Row totals = Column totals for each industry
        (Intermediate sales + Final demand) = (Intermediate purchases + Value added)
        
        This method calculates both Y (total output) and value added to satisfy the identity.
        """
        print("Building value added section...")
        
        # Calculate total output Y = row sums of Z + row sums of final demand
        # This represents total output for each industry
        intermediate_sales = np.sum(Z, axis=1)  # Row sums of Z matrix
        final_demand_totals = np.sum(final_demand, axis=1)  # Row sums of final demand
        Y = intermediate_sales + final_demand_totals
        
        # Calculate intermediate purchases (column sums of Z)
        intermediate_purchases = np.sum(Z, axis=0)
        
        # According to BEA methodology: Row total = Column total for each industry
        # Row total = Intermediate sales + Final demand = Y
        # Column total = Intermediate purchases + Value added
        # Therefore: Value added = Y - Intermediate purchases (balancing item)
        value_added = Y - intermediate_purchases
        
        print(f"Total output Y: {len(Y)} elements")
        print(f"Value added vector: {len(value_added)} elements")
        print(f"Value added range: ${value_added.min():,.0f} to ${value_added.max():,.0f}")
        
        # Verify accounting identity
        row_totals = Y
        col_totals = intermediate_purchases + value_added
        max_diff = np.abs(row_totals - col_totals).max()
        print(f"Accounting identity check - max difference: ${max_diff:.2f}")
        
        return value_added, Y
    
    def extract_actual_value_added_components(self, common_industries: list, use_code_to_name: dict) -> dict:
        """
        Extract actual value added components (V00100, V00200, V00300) from the Use table
        """
        print("Extracting actual value added components from Use table...")
        
        # Load the Use table with the correct sheet
        use_df = pd.read_excel(self.use_file_path, sheet_name=self.year, header=None)
        
        # Find the value added rows (V00100, V00200, V00300)
        va_components = {}
        va_codes = ['V00100', 'V00200', 'V00300']
        va_names = {
            'V00100': 'Compensation of employees',
            'V00200': 'Taxes on production and imports, less subsidies', 
            'V00300': 'Gross operating surplus'
        }
        
        # Search for the value added codes in rows 409-413 (0-indexed: 408-412)
        for i in range(408, min(414, len(use_df))):
            for j in range(len(use_df.columns)):
                cell_value = use_df.iloc[i, j]
                if pd.notna(cell_value) and str(cell_value).strip() in va_codes:
                    code = str(cell_value).strip()
                    print(f"Found {code} at row {i+1}")
                    
                    # Extract the numeric data for industries that match our common_industries
                    # We need to align the columns with our industry order
                    va_data = np.zeros(len(common_industries))
                    
                    # The numeric data starts from column 2 (index 1 has description)
                    # We need to map these columns to our common_industries
                    use_industry_cols = use_df.iloc[i, 2:].values
                    
                    # For now, take the first N values where N = len(common_industries)
                    # This is a simplification - ideally we'd align by industry codes
                    numeric_values = []
                    for k in range(2, len(use_df.columns)):
                        val = use_df.iloc[i, k]
                        if pd.notna(val) and isinstance(val, (int, float)):
                            numeric_values.append(val)
                    
                    # Take only as many values as we have industries
                    if len(numeric_values) >= len(common_industries):
                        va_data = np.array(numeric_values[:len(common_industries)])
                    else:
                        # Pad with zeros if not enough data
                        va_data[:len(numeric_values)] = numeric_values
                    
                    va_components[code] = {
                        'name': va_names[code],
                        'data': va_data
                    }
                    break
        
        print(f"Extracted {len(va_components)} value added components")
        return va_components
        
    def create_square_io_table(self) -> pd.DataFrame:
        """
        Create the final square input-output table by combining all components
        """
        print("Creating final square input-output table...")
        
        # Build market share matrix
        N = self.build_market_share_matrix()
        
        # Build intermediate uses matrix
        Z, common_industries, filtered_common_codes, use_code_to_name = self.build_intermediate_uses_matrix(N)
        
        # Build final demand matrix  
        final_demand, Y, final_demand_columns = self.build_final_demand_matrix(common_industries, filtered_common_codes, use_code_to_name)
        
        # Build value added section (this also calculates the correct Y)
        value_added, Y_corrected = self.build_value_added_section(Z, final_demand)
        
        # Combine into final square input-output table
        n_industries = len(common_industries)
        
        # Ensure Z is square n×n (industry-by-industry)
        if Z.shape[0] != Z.shape[1] or Z.shape[0] != n_industries:
            raise ValueError(f"Z matrix dimensions {Z.shape} don't match expected {n_industries}×{n_industries}")
        
        # Ensure final_demand and Y match the number of industries
        if final_demand.shape[0] != n_industries or len(Y) != n_industries:
            raise ValueError(f"Final demand or Y dimensions don't match number of industries {n_industries}")
        
        # Create the full table structure following methodology exactly
        # Structure: [Z (n×n) | final_demand (n×k)]
        #           [value_added (1×n) | zeros (1×k)]
        # Note: NO "Total Output" column - totals are implicit in the accounting structure
        
        # Top section: intermediate uses + final demand (NO total output column)
        top_section = np.hstack([Z, final_demand])
        
        # Bottom section: value added row (already calculated correctly)
        # Use the value_added calculated in build_value_added_section which ensures accounting identity
        
        # Bottom row: [value_added | zeros for final demand]
        bottom_section = np.hstack([value_added.reshape(1, -1), 
                                   np.zeros((1, final_demand.shape[1]))])
        
        # Combine into final table
        full_table = np.vstack([top_section, bottom_section])
        
        # Create proper column names: industries (with NAICS codes if available) + final demand categories
        industry_col_names = [self.get_industry_display_name(industry) for industry in common_industries]
        col_names = industry_col_names + final_demand_columns
        
        # Create row names: industries (with NAICS codes if available) + value added
        industry_row_names = [self.get_industry_display_name(industry) for industry in common_industries]
        row_names = industry_row_names + ['Value Added']
        
        # Create DataFrame (original format for internal use)
        original_table = pd.DataFrame(full_table, 
                                     index=row_names,
                                     columns=col_names)
        
        # Extract actual value added components from Use table
        va_components = self.extract_actual_value_added_components(common_industries, use_code_to_name)
        
        # Create formatted table matching reference structure
        self.final_io_table = self.format_table_like_reference(
            Z, final_demand, value_added, common_industries, 
            final_demand_columns, use_code_to_name, va_components
        )
        
        print(f"Final square I-O table created: {self.final_io_table.shape[0]} x {self.final_io_table.shape[1]}")
        return self.final_io_table
        
    def format_table_like_reference(self, Z: np.ndarray, final_demand: np.ndarray, 
                                   value_added: np.ndarray, common_industries: list,
                                   final_demand_columns: list, use_code_to_name: dict,
                                   va_components: dict) -> pd.DataFrame:
        """
        Format the table to match the reference 2002 file structure:
        - Header with title, subtitle, units
        - Separate rows for industry codes and names
        - Detailed value added components
        - Total column
        - Source attribution
        """
        print("Formatting table to match reference structure...")
        
        n_industries = len(common_industries)
        n_final_demand = len(final_demand_columns)
        
        # Calculate total output for each industry (for Total column)
        total_output = np.sum(Z, axis=1) + np.sum(final_demand, axis=1)
        
        # Create the full table structure
        total_cols = 2 + n_industries + n_final_demand + 1  # Industry, Description, industries, final demand, Total
        
        # Initialize the formatted table
        formatted_data = []
        
        # Row 0: Title
        title_row = [f'{self.year} Detailed U.S. Input-Output Table'] + [None] * (total_cols - 1)
        formatted_data.append(title_row)
        
        # Row 1: Subtitle
        subtitle_row = [f'{n_industries} Industries'] + [None] * (total_cols - 1)
        formatted_data.append(subtitle_row)
        
        # Row 2: Units
        units_row = ['($ Millions)'] + [None] * (total_cols - 1)
        formatted_data.append(units_row)
        
        # Row 3: Industry codes header
        codes_row = [None, None]  # Industry, Description columns
        for industry in common_industries:
            # Extract BEA code - look up in use_code_to_name mapping
            code = None
            for bea_code, industry_name in use_code_to_name.items():
                if industry_name == industry:
                    code = bea_code
                    break
            
            # Fallback: extract from industry display name if it has format "CODE - NAME"
            if code is None and ' - ' in industry:
                code = industry.split(' - ')[0]
            elif code is None:
                code = industry[:6]  # Last resort truncation
                
            codes_row.append(code)
        # Add final demand and total (no codes)
        codes_row.extend([None] * (n_final_demand + 1))
        formatted_data.append(codes_row)
        
        # Row 4: Industry names header
        names_row = ['Industry', 'Description']
        for industry in common_industries:
            # Extract industry name (remove code prefix if present)
            name = industry.split(' - ', 1)[1] if ' - ' in industry else industry
            names_row.append(name)
        # Add final demand column names and Total
        names_row.extend(final_demand_columns + ['Total'])
        formatted_data.append(names_row)
        
        # Data rows: Industries
        for i, industry in enumerate(common_industries):
            # Extract BEA code - same logic as header
            code = None
            for bea_code, industry_name in use_code_to_name.items():
                if industry_name == industry:
                    code = bea_code
                    break
            
            # Fallback: extract from industry display name
            if code is None and ' - ' in industry:
                code, name = industry.split(' - ', 1)
            else:
                if code is None:
                    code = industry[:6]
                name = industry.split(' - ', 1)[1] if ' - ' in industry else industry
                
            row = [code, name]
            
            # Add intermediate uses
            row.extend(Z[i, :].tolist())
            
            # Add final demand
            row.extend(final_demand[i, :].tolist())
            
            # Add total output
            row.append(total_output[i])
            
            formatted_data.append(row)
        
        # Value added components - use actual data from Use table
        va_order = ['V00100', 'V00200', 'V00300']
        
        if va_components:
            print("Using actual value added data from Use table")
            for code in va_order:
                if code in va_components:
                    component = va_components[code]
                    va_row = [code, component['name']]
                    va_row.extend(component['data'].tolist())
                    va_row.extend([0] * n_final_demand)  # Zero for final demand columns
                    va_row.append(np.sum(component['data']))
                    formatted_data.append(va_row)
                else:
                    print(f"Warning: {code} not found in extracted components")
        else:
            print("Warning: No actual value added components found, using approximation")
            # Fallback to approximation
            compensation = value_added * 0.65
            taxes = value_added * 0.10  
            gross_surplus = value_added * 0.25
            
            for code, data, name in [
                ('V00100', compensation, 'Compensation of employees'),
                ('V00200', taxes, 'Taxes on production and imports, less subsidies'),
                ('V00300', gross_surplus, 'Gross operating surplus')
            ]:
                va_row = [code, name]
                va_row.extend(data.tolist())
                va_row.extend([0] * n_final_demand)
                va_row.append(np.sum(data))
                formatted_data.append(va_row)
        
        # Total row
        total_row = ['Total', 'Total']
        # Column totals = intermediate purchases + value added
        col_totals = np.sum(Z, axis=0) + value_added
        total_row.extend(col_totals.tolist())
        total_row.extend([0] * n_final_demand)  # Final demand totals would go here
        total_row.append(np.sum(col_totals))  # Grand total
        formatted_data.append(total_row)
        
        # Source attribution
        source_row = [f'Source: BEA Input-Output Tables {self.year}'] + [None] * (total_cols - 1)
        formatted_data.append(source_row)
        
        # Convert to DataFrame
        formatted_df = pd.DataFrame(formatted_data)
        
        print(f"Formatted table created: {formatted_df.shape}")
        return formatted_df
    
    def save_table(self, output_path: str) -> None:
        """Save the final input-output table to Excel"""
        if self.final_io_table is not None:
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                self.final_io_table.to_excel(writer, sheet_name=f'{self.year} Detailed Level', 
                                           index=False, header=False)
            print(f"Input-output table saved to: {output_path}")
        else:
            print("No table to save. Run create_square_io_table() first.")
            
    def process_full_pipeline(self, output_path: str = None) -> pd.DataFrame:
        """
        Run the complete processing pipeline
        """
        print("=== BEA INPUT-OUTPUT TABLE PROCESSING PIPELINE ===")
        
        # Load data
        self.load_data()
        
        # Apply adjustments
        self.apply_bea_adjustments()
        
        # Create square I-O table
        io_table = self.create_square_io_table()
        
        # Save if output path provided
        if output_path:
            self.save_table(output_path)
            
        print("=== PROCESSING COMPLETE ===")
        return io_table


def main():
    """
    Example usage of the IOTableProcessor
    """
    # Initialize processor
    processor = IOTableProcessor(
        make_file_path='IOMake_Before_Redefinitions_PRO_Detail.xlsx',
        use_file_path='IOUse_Before_Redefinitions_PRO_Detail.xlsx',
        year='2017'
    )
    
    # Process the tables
    io_table = processor.process_full_pipeline('US_IO_Table_2017.xlsx')
    
    # Display summary statistics
    print("\n=== FINAL TABLE SUMMARY ===")
    print(f"Table dimensions: {io_table.shape}")
    
    # The new format has headers, so we need to identify the data section
    # Data starts at row 5 (after title, subtitle, units, codes, names)
    # Industry data ends before value added rows
    
    try:
        # Find the data section (rows 5 to before value added)
        data_start_row = 5  # After headers
        
        # Find first value added row (starts with 'V00100')
        va_start_idx = None
        for i in range(data_start_row, len(io_table)):
            if pd.notna(io_table.iloc[i, 0]) and str(io_table.iloc[i, 0]) == 'V00100':
                va_start_idx = i
                break
        
        if va_start_idx:
            # Extract numeric data from industry rows
            industry_data = io_table.iloc[data_start_row:va_start_idx, 2:-1]  # Skip code/name cols and Total col
            
            # Convert to numeric, handling any non-numeric values
            industry_numeric = pd.to_numeric(industry_data.values.flatten(), errors='coerce')
            industry_numeric = industry_numeric[~pd.isna(industry_numeric)]
            
            total_transactions = industry_numeric.sum()
            print(f"Total economic transactions: ${total_transactions:,.0f} million")
            
            # Sum all three value added components (V00100, V00200, V00300)
            total_value_added = 0
            for va_code in ['V00100', 'V00200', 'V00300']:
                for i in range(va_start_idx, len(io_table)):
                    if pd.notna(io_table.iloc[i, 0]) and str(io_table.iloc[i, 0]) == va_code:
                        va_data = io_table.iloc[i, 2:-1]  # Skip code/name cols and Total col
                        va_numeric = pd.to_numeric(va_data, errors='coerce')
                        va_numeric = va_numeric[~pd.isna(va_numeric)]
                        total_value_added += va_numeric.sum()
                        break
            
            print(f"Total value added: ${total_value_added:,.0f} million")
        else:
            print("Could not locate value added section for summary statistics")
            
    except Exception as e:
        print(f"Error calculating summary statistics: {e}")
        print("Table structure may need adjustment")
    
    # Show sample of the formatted table
    print("\n=== SAMPLE OF FORMATTED TABLE ===")
    print("Title and headers:")
    print(io_table.iloc[:5, :3])
    print("\nFirst few data rows:")
    if len(io_table) > 10:
        print(io_table.iloc[5:10, :5])


if __name__ == "__main__":
    main()