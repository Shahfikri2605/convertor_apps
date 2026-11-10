import pandas as pd
from io import BytesIO

def process_zao_item_sheets(excel_file_or_bytes, target_sheets=None):
    """
    Reads specified item sheets from ZAO excel file, normalizes columns,
    cleans item codes, standardizes dates, and merges them into one DataFrame.
    """
    if target_sheets is None:
        target_sheets = ['ZAO (FRUITS)_ITEM', 'ZAO (VEG)-ECOM_ITEM']
        
    excel_obj = pd.ExcelFile(excel_file_or_bytes)
    all_dfs = []
    
    def format_item_code(val):
        if pd.isna(val):
            return ""
        if isinstance(val, (int, float)):
            return str(int(val))
        val_str = str(val).strip()
        if val_str.endswith('.0'):
            return val_str[:-2]
        return val_str

    for s_name in target_sheets:
        if s_name not in excel_obj.sheet_names:
            continue
            
        df = pd.read_excel(excel_obj, sheet_name=s_name)
        
        # Strip trailing/leading spaces from headers
        df.columns = [str(c).strip() for c in df.columns]
        
        # Standardize column name: ITEMCODE -> ITEM CODE
        df.rename(columns={'ITEMCODE': 'ITEM CODE'}, inplace=True)
        
        # Filter out summary/total rows at the bottom
        df = df[df['DESCRIPTION'].notna()]
        df = df[~df['ITEM CODE'].astype(str).str.strip().str.upper().isin(['TOTAL', 'NAN', ''])]
        df = df[~df['DATE'].astype(str).str.strip().str.upper().isin(['TOTAL', 'NAN', ''])]
        
        # Format item codes cleanly (avoid 2553585.0)
        df['ITEM CODE'] = df['ITEM CODE'].apply(format_item_code)
        
        # Standardize dates to DD/MM/YYYY
        df['DATE'] = pd.to_datetime(df['DATE'], dayfirst=True, errors='coerce').dt.strftime('%d/%m/%Y')
        
        # Clean numeric columns
        df['QTY'] = pd.to_numeric(df['QTY'].astype(str).str.replace(',', ''), errors='coerce').fillna(0.0)
        df['SALES BEF GST'] = pd.to_numeric(df['SALES BEF GST'].astype(str).str.replace(',', ''), errors='coerce').fillna(0.0)
        
        # Tag origin sheet
        df['SOURCE_SHEET'] = s_name
        
        # Uniform column ordering
        cols_order = [
            'SOURCE_SHEET', 'DEPT', 'YEAR', 'Vendor', 'OUTLET', 
            'DATE', 'ITEM CODE', 'DESCRIPTION', 'QTY', 'SALES BEF GST'
        ]
        
        # Keep only existing standard columns
        valid_cols = [c for c in cols_order if c in df.columns]
        all_dfs.append(df[valid_cols])
        
    if not all_dfs:
        return pd.DataFrame()
        
    combined_df = pd.concat(all_dfs, ignore_index=True)
    return combined_df


def export_zao_to_excel(df):
    """Exports the merged ZAO data into a formatted Excel spreadsheet."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='ZAO Combined', index=False)
        workbook = writer.book
        worksheet = writer.sheets['ZAO Combined']
        
        # Cell Formats
        hdr_fmt = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        date_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
        text_fmt = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
        code_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
        qty_fmt = workbook.add_format({'num_format': '#,##0.000', 'align': 'right', 'valign': 'vcenter'})
        val_fmt = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
        
        # Apply header formatting
        for col_idx, col_name in enumerate(df.columns):
            worksheet.write(0, col_idx, col_name, hdr_fmt)
            
        # Set column widths & formatting
        worksheet.set_column('A:A', 24, text_fmt)   # SOURCE_SHEET
        worksheet.set_column('B:B', 14, text_fmt)   # DEPT
        worksheet.set_column('C:C', 10, code_fmt)   # YEAR
        worksheet.set_column('D:D', 35, text_fmt)   # Vendor
        worksheet.set_column('E:E', 10, code_fmt)   # OUTLET
        worksheet.set_column('F:F', 14, date_fmt)   # DATE
        worksheet.set_column('G:G', 16, code_fmt)   # ITEM CODE
        worksheet.set_column('H:H', 45, text_fmt)   # DESCRIPTION
        worksheet.set_column('I:I', 12, qty_fmt)    # QTY
        worksheet.set_column('J:J', 16, val_fmt)    # SALES BEF GST
        
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
        worksheet.freeze_panes(1, 0)
        
    output.seek(0)
    return output
