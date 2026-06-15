import pandas as pd
from io import BytesIO

def process_ntuc_files(qty_file_bytes, sales_file_bytes):
    """
    Combines NTUC Quantity and Sales CSV reports, 
    unpivots the horizontal dates, and parses codes/descriptions.
    """
    # FIX: Added encoding='utf-16' to handle the 0xff Byte Order Mark safely
    df_qty = pd.read_csv(BytesIO(qty_file_bytes), sep='\t', header=1, encoding='utf-16')
    df_sales = pd.read_csv(BytesIO(sales_file_bytes), sep='\t', header=1, encoding='utf-16')
    
    id_vars = ['1st Column', '2nd Column', 'Metric']
    
    # Isolate all date columns dynamically
    date_cols_qty = [c for c in df_qty.columns if c not in id_vars]
    date_cols_sales = [c for c in df_sales.columns if c not in id_vars]
    
    # Melt wide date columns into vertical rows
    df_qty_long = df_qty.melt(id_vars=id_vars, value_vars=date_cols_qty, var_name='date', value_name='quantity')
    df_sales_long = df_sales.melt(id_vars=id_vars, value_vars=date_cols_sales, var_name='date', value_name='sales')
    
    # Drop the structural metric string columns
    df_qty_long = df_qty_long.drop(columns=['Metric'])
    df_sales_long = df_sales_long.drop(columns=['Metric'])
    
    # Force convert metrics to safe numeric data types
    df_qty_long['quantity'] = pd.to_numeric(df_qty_long['quantity'].astype(str).str.replace(',', ''), errors='coerce').fillna(0.0)
    df_sales_long['sales'] = pd.to_numeric(df_sales_long['sales'].astype(str).str.replace(',', ''), errors='coerce').fillna(0.0)
    
    # Outer join both datasets across keys
    df_merged = pd.merge(df_qty_long, df_sales_long, on=['1st Column', '2nd Column', 'date'], how='outer')
    df_merged['quantity'] = df_merged['quantity'].fillna(0.0)
    df_merged['sales'] = df_merged['sales'].fillna(0.0)
    
    # Strip completely blank inactive transaction rows
    df_merged = df_merged[(df_merged['quantity'] != 0) | (df_merged['sales'] != 0)]
    
    if df_merged.empty:
        return pd.DataFrame(columns=['date', 'location code', 'location name', 'item code','description','sales', 'quantity'])

    # Parse '1st Column' -> separate location code from location name
    def parse_location(loc_str):
        if pd.isna(loc_str):
            return "", ""
        loc_str = str(loc_str)
        if " - " in loc_str:
            parts = loc_str.split(" - ", 1)
            return parts[0].strip(), parts[1].strip()
        return loc_str.strip(), ""

    loc_parsed = df_merged['1st Column'].apply(parse_location)
    df_merged['location code'] = [x[0] for x in loc_parsed]
    df_merged['location name'] = [x[1] for x in loc_parsed]
    
    # Parse '2nd Column' -> separate item description from suffix internal identifier codes
    def parse_item_details(prod_str):
        if pd.isna(prod_str):
            return "", ""
        prod_str = str(prod_str)
        if " - " in prod_str:
            parts = prod_str.rsplit(" - ", 1)
            return parts[0].strip(), parts[1].strip()
        return prod_str.strip(), ""
    
    prod_parsed = df_merged['2nd Column'].apply(parse_item_details)
    df_merged['item code'] = [x[1] for x in prod_parsed]
    df_merged['description'] = [x[0] for x in prod_parsed]
    
    # Order layout exactly as requested
    final_cols = ['date', 'location code', 'location name','item code', 'description', 'sales', 'quantity']
    df_final = df_merged[final_cols].reset_index(drop=True)
    
    # Sort data layout logically
    df_final.sort_values(by=['date', 'location code', 'description'], inplace=True, ignore_index=True)
    
    return df_final


def export_to_excel_formatted(df):
    """Generates a beautifully structured and cleaned layout binary Excel sheet."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    
    df.to_excel(writer, sheet_name='NTUC Combined', index=False)
    
    workbook = writer.book
    worksheet = writer.sheets['NTUC Combined']
    
    # Styling configurations
    format_qty = workbook.add_format({'num_format': '#,##0', 'align': 'right', 'valign': 'vcenter'})
    format_val = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_text = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
    format_center = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
    format_header = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, format_header)
        
    # Match clean layout width sizes
    worksheet.set_column('A:A', 14, format_center)  # date
    worksheet.set_column('B:B', 15, format_center)  # location code
    worksheet.set_column('C:C', 30, format_text)
    worksheet.set_column('D:D', 20, format_center)    # location name
    worksheet.set_column('E:E', 45, format_text)    # description
    worksheet.set_column('F:F', 14, format_val)     # sales
    worksheet.set_column('G:G', 14, format_qty)     # quantity
    
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
    worksheet.freeze_panes(1, 0)
    
    writer.close()
    output.seek(0)
    return output
