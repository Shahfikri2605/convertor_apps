import pandas as pd
from io import BytesIO

def process_lazada_files(uploaded_files):
    """
    Combines multiple weekly Lazada Transaction files (.xlsx or .csv).
    Creates a Horizontal Summary broken down BY FILE.
    """
    all_dfs = []
    
    for file in uploaded_files:
        try:
            # 1. Read File
            if file.name.lower().endswith('.csv'):
                try:
                    df = pd.read_csv(file)
                except UnicodeDecodeError:
                    file.seek(0)
                    df = pd.read_csv(file, encoding='ISO-8859-1')
            else:
                df = pd.read_excel(file)
            
            # 2. Clean Junk Columns
            valid_cols = [c for c in df.columns if not str(c).startswith('Unnamed') and c not in ['Row Labels', 'Sum of Amount']]
            df = df[valid_cols]
            
            # Drop empty rows
            if 'Transaction Date' in df.columns:
                df = df.dropna(subset=['Transaction Date'])
            
            # 3. Add the File Name
            df.insert(0, 'Source File', file.name)
            all_dfs.append(df)
            
        except Exception as e:
            print(f"Error reading {file.name}: {e}")
            
    if not all_dfs:
        return None, None
        
    # 4. COMBINE ALL WEEKS
    df_combined = pd.concat(all_dfs, ignore_index=True)
    
    # Ensure Amount is numeric
    if 'Amount' in df_combined.columns:
        df_combined['Amount'] = pd.to_numeric(df_combined['Amount'], errors='coerce').fillna(0)
    
    # Sort by Date
    if 'Transaction Date' in df_combined.columns and 'Statement' in df_combined.columns:
        df_combined['temp_date'] = pd.to_datetime(df_combined['Transaction Date'], errors='coerce')
        df_combined = df_combined.sort_values(by=['temp_date', 'Statement']).drop(columns=['temp_date'])
    
    # 5. CREATE PER-FILE HORIZONTAL SUMMARY
    if 'Fee Name' in df_combined.columns and 'Amount' in df_combined.columns:
        # Group by File AND Fee Name
        grouped = df_combined.groupby(['Source File', 'Fee Name'])['Amount'].sum().reset_index()
        
        # Pivot the table: Files as rows, Fees as columns
        pivot_summary = grouped.pivot(index='Source File', columns='Fee Name', values='Amount').fillna(0)
        
        # Add a TOTAL column for each file (summing across the row)
        pivot_summary['TOTAL PAYOUT'] = pivot_summary.sum(axis=1)
        
        # Add a GRAND TOTAL row for the bottom (summing down the columns)
        pivot_summary.loc['GRAND TOTAL'] = pivot_summary.sum(axis=0)
        
        # Reset index so 'Source File' becomes a normal column again for Excel
        pivot_summary = pivot_summary.reset_index()
    else:
        pivot_summary = pd.DataFrame({'Message': ['Fee Name or Amount column missing']})
    
    # 6. WRITE & STYLE EXCEL
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pivot_summary.to_excel(writer, index=False, sheet_name='Summary')
        df_combined.to_excel(writer, index=False, sheet_name='Combined_Transactions')
        
        workbook = writer.book
        ws_summary = writer.sheets['Summary']
        ws_raw = writer.sheets['Combined_Transactions']
        
        # --- Styles ---
        money_fmt = workbook.add_format({'num_format': '#,##0.00'})
        header_fmt = workbook.add_format({'bold': True, 'bottom': 1, 'text_wrap': True, 'align': 'center', 'valign': 'vcenter'})
        total_fmt = workbook.add_format({'bold': True, 'num_format': '#,##0.00', 'bg_color': '#EAEAEA'}) 
        bold_label = workbook.add_format({'bold': True, 'bg_color': '#EAEAEA'})
        
        # --- Format Summary Sheet ---
        num_cols = len(pivot_summary.columns)
        num_rows = len(pivot_summary)
        
        # Write Headers and set column widths
        for col_num, value in enumerate(pivot_summary.columns.values):
            ws_summary.write(0, col_num, value, header_fmt)
            if col_num == 0:
                ws_summary.set_column(col_num, col_num, 40) # Source File column wide
            else:
                ws_summary.set_column(col_num, col_num, 15, money_fmt) # Money columns
                
        # Apply gray background formatting to the "TOTAL PAYOUT" column (last column)
        if num_cols > 1:
            for row_num in range(1, num_rows + 1):
                val = pivot_summary.iloc[row_num-1, num_cols-1]
                ws_summary.write(row_num, num_cols-1, val, total_fmt)
                
        # Apply gray background formatting to the "GRAND TOTAL" row (last row)
        if num_rows > 0:
            ws_summary.write(num_rows, 0, 'GRAND TOTAL', bold_label)
            for col_num in range(1, num_cols):
                val = pivot_summary.iloc[num_rows-1, col_num]
                ws_summary.write(num_rows, col_num, val, total_fmt)
        
        # --- Format Combined Transactions Sheet ---
        ws_raw.set_column('A:A', 35)              # Source File Name (Wide)
        ws_raw.set_column('B:C', 18)              # Date and Fee Name
        ws_raw.set_column('D:D', 15, money_fmt)   # Amount Column
        ws_raw.set_column('E:Z', 20)              # Everything else
        
    return output, df_combined
