import pandas as pd
from io import BytesIO

def process_boost_files(uploaded_files, report_month, outlet_name, company_name, bank_account):
    """
    Combines Boost CSVs and formats them into a specific Excel layout.
    Returns: BytesIO object (The Excel file) and the Preview Dataframe.
    """
    all_dfs = []
    
    # 1. READ & COMBINE
    for uploaded_file in uploaded_files:
        try:
            # Read CSV
            df = pd.read_csv(uploaded_file)
            # Clean column names (remove spaces)
            df.columns = df.columns.str.strip()
            all_dfs.append(df)
        except Exception as e:
            print(f"Error reading {uploaded_file.name}: {e}")
            continue
    
    if not all_dfs:
        return None, None

    # Concatenate
    df_combined = pd.concat(all_dfs, ignore_index=True)
    
    # Check for Date column
    if 'Date Time' not in df_combined.columns:
        raise ValueError(f"Column 'Date Time' not found. Found: {list(df_combined.columns)}")

    # 2. CLEAN & SORT
    # Robust Date Conversion
    df_combined['Date Time'] = pd.to_datetime(df_combined['Date Time'], errors='coerce')
    df_combined = df_combined.dropna(subset=['Date Time'])
    
    if df_combined.empty:
        return None, None

    # Sort by Date
    df_combined = df_combined.sort_values(by='Date Time')
    
    # 3. MAP COLUMNS
    df_target = pd.DataFrame()
    df_target['DATE'] = df_combined['Date Time'].dt.strftime('%d/%m/%Y')
    df_target['OUTLET ID'] = df_combined['Outlet ID']
    df_target['DESCRIPTION'] = 'BOOST'
    df_target['AMOUNT'] = df_combined['Transaction Amount']
    df_target['COMMISSION'] = df_combined['Boost MDR Amount']
    df_target['BANK'] = df_combined['Net Amount']
    
    # 4. EXCEL FORMATTING STRUCTURE
    # Rows 0-8 are Header Info
    # Row 9 is Table Header (DATE, DESC...)
    # Row 10 is Units (RM...)
    
    header_rows = [
        [None, None, None, None, None, None], # Row 1
        [None, None, None, None, None, None], # Row 2
        [None, company_name, None, None, None, None], # Row 3
        [None, bank_account, None, None, None, None], # Row 4
        [None, None, None, None, None, None], # Row 5
        [None, report_month, None, None, None, None], # Row 6
        [None, None, None, None, None, None], # Row 7
        [None, outlet_name, None, None, None, None], # Row 8
        [None, None, None, None, None, None], # Row 9
        [None, 'DATE','OUTLET ID', 'DESCRIPTION ', 'AMOUNT', 'COMMISSION ', 'BANK'], # Row 10
        [None, None, None, 'RM', 'RM', 'RM'] # Row 11
    ]
    
    # Prepare data part with indentation (None at col 0)
    df_target_values = df_target.values.tolist()
    data_rows = [[None] + row for row in df_target_values]
    
    # Combine all rows
    final_rows = header_rows + data_rows
    df_final = pd.DataFrame(final_rows)
    
    # 5. WRITE & STYLE EXCEL
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Write data without default header/index
        df_final.to_excel(writer, index=False, header=False, sheet_name='Sheet1')
        
        # Get workbook objects
        workbook = writer.book
        worksheet = writer.sheets['Sheet1']
        
        # --- STYLES ---
        border_fmt = workbook.add_format({
            'border': 1,       # Thin border
            'align': 'center', 
            'valign': 'vcenter'
        })
        bold_fmt = workbook.add_format({'bold': True})
        
        # --- APPLY STYLES ---
        # Apply Borders to Table (Row 10 downwards)
        start_row = 9 
        end_row = len(final_rows) - 1
        start_col = 1 # Column B
        end_col = 6   # Column F
        
        # Apply border to the data range
        # Note: xlsxwriter conditional_format is robust for ranges
        worksheet.conditional_format(start_row, start_col, end_row, end_col, {
            'type': 'no_errors',
            'format': border_fmt
        })

        # Apply Bold Headers
        worksheet.write(2, 1, company_name, bold_fmt)
        worksheet.write(3, 1, bank_account, bold_fmt)
        worksheet.write(5, 1, report_month, bold_fmt)
        worksheet.write(7, 1, outlet_name, bold_fmt)

        # Column Widths
        worksheet.set_column('A:A', 2)
        worksheet.set_column('B:B', 15)
        worksheet.set_column('C:C', 20)
        worksheet.set_column('D:F', 15)

    return output, df_target
