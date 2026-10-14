import pandas as pd
from io import BytesIO

def process_single_settlement_file(file_input, source_file_name="Unknown"):
    """
    Reads a single settlement Excel file (.xlsx) from BytesIO, Streamlit UploadedFile, or path.
    Extracts: Settlement Date, Transaction Datetime, Outlet, Transaction Reference, Transaction Amount.
    """
    if isinstance(file_input, bytes):
        file_input = BytesIO(file_input)
        
    df_raw = pd.read_excel(file_input, header=None)
    
    # 1. Locate the table header row
    header_row_idx = None
    for r in range(min(20, len(df_raw))):
        row_vals = [str(x).strip().upper() for x in df_raw.iloc[r].dropna().tolist()]
        if any("SETTLEMENT DATE" in v for v in row_vals) and any("TRANSACTION DATETIME" in v for v in row_vals):
            header_row_idx = r
            break
            
    if header_row_idx is None:
        return pd.DataFrame()
        
    # 2. Extract column headers and data rows
    headers = [str(x).strip() if pd.notna(x) else f"col_{i}" for i, x in enumerate(df_raw.iloc[header_row_idx])]
    df_data = df_raw.iloc[header_row_idx + 1:].copy()
    df_data.columns = headers
    
    # 3. Filter out summary/footer rows like 'TOTAL:'
    no_col = headers[0]
    df_data = df_data[pd.to_numeric(df_data[no_col], errors='coerce').notna()]
    
    # 4. Map columns dynamically
    col_map = {}
    for col in df_data.columns:
        col_upper = col.upper()
        if "SETTLEMENT DATE" in col_upper:
            col_map["Settlement Date"] = col
        elif "TRANSACTION DATETIME" in col_upper or "TRANSACTION DATE TIME" in col_upper:
            col_map["Transaction Datetime"] = col
        elif "OUTLET NAME" in col_upper:
            col_map["Outlet"] = col
        elif "TRANSACTION REFERENCE" in col_upper:
            col_map["Transaction Reference"] = col
        elif "TRANSACTION AMOUNT" in col_upper:
            col_map["Transaction Amount"] = col

    required_keys = ["Settlement Date", "Transaction Datetime", "Outlet", "Transaction Reference", "Transaction Amount"]
    if not all(k in col_map for k in required_keys):
        return pd.DataFrame()

    subset = df_data[[col_map[k] for k in required_keys]].copy()
    subset.columns = required_keys
    subset["Source File"] = source_file_name

    # Clean numeric amounts
    subset["Transaction Amount"] = (
        subset["Transaction Amount"]
        .astype(str)
        .str.replace(',', '', regex=True)
    )
    subset["Transaction Amount"] = pd.to_numeric(subset["Transaction Amount"], errors='coerce')

    return subset


def export_settlements_to_excel(df):
    """Formats and exports the combined settlement DataFrame into an Excel file."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Settlements', index=False)
        workbook = writer.book
        worksheet = writer.sheets['Settlements']
        
        # Styles
        hdr_fmt = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        date_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
        curr_fmt = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
        text_fmt = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
        
        # Format headers
        for col_idx, col_name in enumerate(df.columns):
            worksheet.write(0, col_idx, col_name, hdr_fmt)
            
        # Column widths & formatting
        worksheet.set_column('A:A', 16, date_fmt)   # Settlement Date
        worksheet.set_column('B:B', 22, date_fmt)   # Transaction Datetime
        worksheet.set_column('C:C', 38, text_fmt)   # Outlet
        worksheet.set_column('D:D', 35, text_fmt)   # Transaction Reference
        worksheet.set_column('E:E', 20, curr_fmt)   # Transaction Amount
        worksheet.set_column('F:F', 30, text_fmt)   # Source File
        
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
        worksheet.freeze_panes(1, 0)
        
    output.seek(0)
    return output
