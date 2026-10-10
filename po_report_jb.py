import pdfplumber
import pandas as pd
import re
from io import BytesIO

def process_zenxin_purchase_report(pdf_path_or_bytes, source_file_name="Unknown"):
    all_purchases = []
    
    if isinstance(pdf_path_or_bytes, bytes):
        pdf_file = BytesIO(pdf_path_or_bytes)
    else:
        pdf_file = pdf_path_or_bytes

    from_date_global = "Unknown Period"
    current_supplier_code = ""
    current_supplier_name = ""

    # Matches supplier code pattern (e.g. 4000/A16, 4001/100)
    sup_code_re = re.compile(r'^\d{4}/[A-Z0-9]+$')
    
    # Matches data rows ending with: Group UOM Quantity Total
    # e.g.: "4 BTL 16.00 1,360.00" or "C TIN 1.00 52.50"
    row_end_re = re.compile(r'\s+([0-9A-Z]{1,3})\s+([A-Za-z/]+(?:\s+[A-Za-z/]+)?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})$')

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            raw_text = page.extract_text() or ""
            
            # 1. Extract Period
            date_match = re.search(r'From\s+Date\s+\[([\d/]+)\]\s+[^\[]+\s+\[([\d/]+)\]', raw_text, re.IGNORECASE)
            if date_match and from_date_global == "Unknown Period":
                from_date_global = f"From Date [{date_match.group(1)}] To [{date_match.group(2)}]"
            
            words = page.extract_words()
            if not words: 
                continue
            
            # 2. Line Assembly
            words.sort(key=lambda w: w['top'])
            lines = []
            current_line = []
            current_top = None
            
            for w in words:
                if current_top is None:
                    current_top = w['top']
                    current_line.append(w)
                elif abs(w['top'] - current_top) < 3.5:
                    current_line.append(w)
                else:
                    lines.append(current_line)
                    current_line = [w]
                    current_top = w['top']
            if current_line:
                lines.append(current_line)
                
            for line in lines:
                line.sort(key=lambda w: w['x0'])
            
            # 3. Parse Lines
            for line in lines:
                if not line:
                    continue
                
                line_text = " ".join([w['text'] for w in line]).strip()
                line_text_upper = line_text.upper()
                
                # Filter Page Headers / Footers
                if any(k in line_text_upper for k in [
                    "PRODUCT PURCHASE REPORT", "SUPPLIER CODE FROM", "TO [ZZZZZZZZZZ]", 
                    "PAGE ", "PRINTED ON", "PRODUCT CODE", "DESCRIPTION", "U.O.M."
                ]):
                    continue

                tokens = [w['text'].strip() for w in line]
                first_token = tokens[0]

                # --- Detect Supplier Header ---
                if sup_code_re.match(first_token) and line[0]['x0'] < 100:
                    current_supplier_code = first_token
                    current_supplier_name = " ".join(tokens[1:]).strip()
                    continue
                elif len(tokens) >= 1 and sup_code_re.match(tokens[0]):
                    current_supplier_code = tokens[0]
                    current_supplier_name = " ".join(tokens[1:]).strip()
                    continue

                # --- Detect Item Data Rows ---
                match = row_end_re.search(line_text)
                if match:
                    # Ignore subtotal / total summary lines
                    if line[0]['x0'] > 85 or any(k in line_text_upper for k in ["TOTAL", "SUBTOTAL", "GRAND"]):
                        continue
                    
                    prod_code = tokens[0]
                    # Make sure first token isn't a misplaced header
                    if sup_code_re.match(prod_code) or prod_code.upper() in ["RENTAL"]:
                        continue

                    group_val = match.group(1).strip()
                    uom_val = match.group(2).strip()
                    qty_val = float(match.group(3).replace(',', ''))
                    total_val = float(match.group(4).replace(',', ''))

                    # Extract description from the segment between product code and row end match
                    prefix_part = line_text[:match.start()].strip()
                    description = prefix_part[len(prod_code):].strip()

                    all_purchases.append({
                        "Source File": source_file_name,
                        "Period": from_date_global,
                        "Supplier Code": current_supplier_code,
                        "Supplier Name": current_supplier_name,
                        "Product Code": prod_code,
                        "Description": description,
                        "Group": group_val,
                        "U.O.M.": uom_val,
                        "Quantity": qty_val,
                        "Total (RM)": total_val
                    })

    df = pd.DataFrame(all_purchases)
    if df.empty:
        return pd.DataFrame(columns=[
            "Source File", "Period", "Supplier Code", "Supplier Name", 
            "Product Code", "Description", "Group", "U.O.M.", "Quantity", "Total (RM)"
        ])
    
    return df


# --- EXCEL EXPORT ---
def export_purchase_to_excel(df):
    """Exports the purchase report DataFrame to formatted Excel file."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    
    df.to_excel(writer, sheet_name='Purchase Report', index=False)
    
    workbook = writer.book
    worksheet = writer.sheets['Purchase Report']
    
    format_qty = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_val = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_text = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
    format_center = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
    format_header = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    
    # Overwrite headers with styling
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, format_header)
    
    # Set explicit column widths
    worksheet.set_column('A:A', 25, format_text)    # Source File
    worksheet.set_column('B:B', 32, format_center)  # Period
    worksheet.set_column('C:C', 16, format_center)  # Supplier Code
    worksheet.set_column('D:D', 35, format_text)    # Supplier Name
    worksheet.set_column('E:E', 18, format_center)  # Product Code
    worksheet.set_column('F:F', 45, format_text)    # Description
    worksheet.set_column('G:G', 10, format_center)  # Group
    worksheet.set_column('H:H', 10, format_center)  # U.O.M.
    worksheet.set_column('I:I', 14, format_qty)     # Quantity
    worksheet.set_column('J:J', 16, format_val)     # Total (RM)
    
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
    worksheet.freeze_panes(1, 0)
    
    writer.close()
    output.seek(0)
    return output
