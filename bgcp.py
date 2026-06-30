import pdfplumber
import pandas as pd
import re
from io import BytesIO

def process_zenxin_sales_report(pdf_path_or_bytes, source_file_name="Unknown"):
    all_products = []
    
    if isinstance(pdf_path_or_bytes, bytes):
        pdf_file = BytesIO(pdf_path_or_bytes)
    else:
        pdf_file = pdf_path_or_bytes

    # Default fallback values for metadata fields
    from_date_global = "From Date [01/05/2026] To [31/05/2026]"
    invoice_no_global = "Unknown"
    invoice_date_global = "Unknown"

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            raw_text = page.extract_text() or ""
            
            # 1. Extract Header Metadata (Dates, Invoice No, Invoice Date)
            date_match = re.search(r'From\s+Date\s+\[([\d/]+)\]\s+To\s+\[([\d/]+)\]', raw_text, re.IGNORECASE)
            if date_match:
                from_date_global = f"From Date [{date_match.group(1)}] To [{date_match.group(2)}]"
                
            inv_no_match = re.search(r'Invoice\s+No\.\s*[\s,"]*:\s*([A-Za-z0-9\-]+)', raw_text, re.IGNORECASE)
            if inv_no_match:
                invoice_no_global = inv_no_match.group(1)
                
            inv_date_match = re.search(r'Invoice\s+Date\s*[\s,"]*:\s*([\d/]+)', raw_text, re.IGNORECASE)
            if inv_date_match:
                invoice_date_global = inv_date_match.group(1)

            words = page.extract_words()
            if not words: 
                continue
            
            # 2. Group word tokens into clean horizontal rows based on visual top coordinates
            words.sort(key=lambda w: w['top'])
            lines = []
            current_line = []
            current_top = None
            
            for w in words:
                if current_top is None:
                    current_top = w['top']
                    current_line.append(w)
                elif abs(w['top'] - current_top) < 4:  # Spatial grouping alignment threshold
                    current_line.append(w)
                else:
                    lines.append(current_line)
                    current_line = [w]
                    current_top = w['top']
            if current_line:
                lines.append(current_line)
                
            for line in lines:
                line.sort(key=lambda w: w['x0'])
                
            # 3. Parse data records line by line
            for line in lines:
                if not line or len(line) < 4: 
                    continue
                
                line_text_upper = " ".join([w['text'].upper() for w in line])
                
                # Structural filter bypass rules
                if any(k in line_text_upper for k in ["PRODUCT SALES REPORT", "PAGE", "PRINTED ON", "CODE DESCRIPTION", "SUMMARY", "QTY SOLD", "GRAND TOTAL", "SUBTOTAL"]):
                    continue
                if "TOTAL" in line_text_upper or "SUB-TOTAL" in line_text_upper:
                    continue
                
                # Look for the visual column structure layout position matching UOM columns to find metrics
                uom_idx = None
                for i in range(len(line) - 1, -1, -1):
                    txt = line[i]['text'].strip().upper()
                    if txt in ['EA', 'BTL', 'UNIT', 'KG', 'PKT', 'BOX', 'CTN']:
                        if i > 0:
                            try:
                                float(line[i-1]['text'].replace(',', ''))
                                uom_idx = i
                                break
                            except ValueError:
                                pass
                
                if uom_idx is None:
                    # If this line has no numeric metrics block, check if it is a secondary continuation line holding a Barcode
                    if all_products and line[0]['x0'] > 60:
                        for token in [w['text'].strip() for w in line]:
                            if token.isdigit() and len(token) >= 12 and not all_products[-1]["Barcode"]:
                                all_products[-1]["Barcode"] = token
                    continue
                
                try:
                    qty = float(line[uom_idx-1]['text'].replace(',', ''))
                    uom = line[uom_idx]['text'].strip()
                    
                    # Read trailing columns to the right of UOM
                    right_values = []
                    for t in line[uom_idx+1:]:
                        clean_val = t['text'].replace(',', '').strip()
                        if clean_val.startswith('(') and clean_val.endswith(')'):
                            clean_val = "-" + clean_val[1:-1]
                        if clean_val.endswith('.'):
                            clean_val = clean_val[:-1]
                        if clean_val:
                            right_values.append(float(clean_val))
                            
                    # Handle rows with or without discount columns dynamically
                    if len(right_values) == 4:    # Price, Dis %, Disc. Amt, Amount
                        unit_price, dis_pct, disc_amt, amount = right_values
                    elif len(right_values) == 2:  # Price, Amount (No Discount columns)
                        unit_price, dis_pct, disc_amt, amount = right_values[0], 0.0, 0.0, right_values[1]
                    else:
                        continue
                        
                    # Split tokens remaining on the left hand side before the Quantity metric column
                    remaining_tokens = line[:uom_idx-1]
                    item_code = ""
                    barcode = ""
                    desc_words = []
                    
                    for t in remaining_tokens:
                        token = t['text'].strip()
                        if token.isdigit():
                            if len(token) >= 12:
                                barcode = token
                            elif 4 <= len(token) <= 8:
                                item_code = token
                            elif token == "0":  # Avoid catching standalone row numbers
                                continue
                        else:
                            desc_words.append(t['text'])
                            
                    description = " ".join(desc_words).strip()
                    
                    # Clean out leading loop counter characters if attached to descriptions
                    if description and description[0].isdigit() and description[1] == " ":
                        description = description[2:].strip()
                        
                    all_products.append({
                        "Source File": source_file_name,
                        "From Date": from_date_global,
                        "Invoice No.": invoice_no_global,
                        "Invoice Date": invoice_date_global,
                        "Item Code": item_code,
                        "Barcode": barcode,
                        "Description": description,
                        "U/M": uom,
                        "Qty Sold": qty,
                        "Unit Price": unit_price,
                        "Discount %": dis_pct,
                        "Discount Amt": disc_amt,
                        "Amount": amount
                    })
                except Exception:
                    continue
                    
    df = pd.DataFrame(all_products)
    if df.empty:
        return pd.DataFrame(columns=["Source File", "From Date", "Invoice No.", "Invoice Date", "Item Code", "Barcode", "Description", "U/M", "Qty Sold", "Unit Price", "Discount %", "Discount Amt", "Amount"])
        
    # Aggregate values to sum up duplicate item values split by system break lines cleanly
    df_grouped = df.groupby(
        ["Source File", "From Date", "Invoice No.", "Invoice Date", "Item Code", "Barcode", "Description", "U/M"], as_index=False
    )[["Qty Sold", "Unit Price", "Discount %", "Discount Amt", "Amount"]].sum()
    
    # Re-enforce requested exact visual order layout mapping
    final_columns = ["Source File", "From Date", "Invoice No.", "Invoice Date", "Item Code", "Barcode", "Description", "U/M", "Qty Sold", "Unit Price", "Discount %", "Discount Amt", "Amount"]
    return df_grouped[final_columns]


# --- ADVANCED EXCEL EXPORT ---
def export_to_excel_perfect_streamlit(df):
    """Saves the flat DataFrame to a beautifully formatted grid Excel sheet."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    
    df.to_excel(writer, sheet_name='Sales Report', index=False)
    
    workbook = writer.book
    worksheet = writer.sheets['Sales Report']
    
    format_qty = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_val = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_text = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
    format_center = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
    format_header = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    
    # Overwrite custom headers with bold grey alignment style block
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, format_header)
    
    # Set explicit structured width sizes matching column contents
    worksheet.set_column('A:A', 32, format_text)    # Source File
    worksheet.set_column('B:B', 38, format_center)  # From Date [01/05/2026] To [31/05/2026]
    worksheet.set_column('C:C', 16, format_center)  # Invoice No.
    worksheet.set_column('D:D', 14, format_center)  # Invoice Date
    worksheet.set_column('E:E', 15, format_center)  # Item Code
    worksheet.set_column('F:F', 18, format_center)  # Barcode
    worksheet.set_column('G:G', 45, format_text)    # Description
    worksheet.set_column('H:H', 10, format_center)  # U/M
    worksheet.set_column('I:I', 14, format_qty)     # Qty Sold
    worksheet.set_column('J:J', 14, format_val)     # Unit Price
    worksheet.set_column('K:K', 14, format_qty)     # Discount %
    worksheet.set_column('L:L', 14, format_val)     # Discount Amt
    worksheet.set_column('M:M', 15, format_val)     # Amount
    
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
    worksheet.freeze_panes(1, 0) 
    
    writer.close()
    output.seek(0)
    return output
