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

    # Default fallback full period phrase if none found in header
    from_date_global = "From Date [01/05/2026] To [31/05/2026]"

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Extract raw text from page to pull metadata from headers
            raw_text = page.extract_text() or ""
            
            # Extract both dates dynamically to reconstruct the full phrase precisely
            date_match = re.search(r'From\s+Date\s+\[([\d/]+)\]\s+[^\[]+\s+\[([\d/]+)\]', raw_text, re.IGNORECASE)
            if date_match:
                from_date_global = f"From Date [{date_match.group(1)}] To [{date_match.group(2)}]"
            
            words = page.extract_words()
            if not words: 
                continue
            
            # 1. Group individual word tokens into horizontal row lines based on top coordinates
            words.sort(key=lambda w: w['top'])
            lines = []
            current_line = []
            current_top = None
            
            for w in words:
                if current_top is None:
                    current_top = w['top']
                    current_line.append(w)
                elif abs(w['top'] - current_top) < 4:  # Tight vertical pixel threshold for straight lines
                    current_line.append(w)
                else:
                    lines.append(current_line)
                    current_line = [w]
                    current_top = w['top']
            if current_line:
                lines.append(current_line)
                
            for line in lines:
                line.sort(key=lambda w: w['x0'])
                
            # 2. Find header layout positions dynamically per page to build column visual centers
            columns_x = {}
            for line in lines:
                line_text = " ".join([w['text'].upper() for w in line])
                if "QTY SOLD" in line_text or "CASH SALES" in line_text:
                    for w in line:
                        txt = w['text'].upper()
                        center_x = (w['x0'] + w['x1']) / 2
                        if "QTY" in txt or "SOLD" in txt:
                            columns_x["Qty Sold"] = center_x
                        elif "INVOICE" in txt:
                            columns_x["Invoice"] = center_x
                        elif "CASH" in txt or "SALES" in txt:
                            columns_x["Cash Sales"] = center_x
                        elif "DEBIT" in txt:
                            columns_x["Debit Note"] = center_x
                        elif "TOTAL" in txt and "GRAND" not in line_text and "SUB" not in line_text:
                            columns_x["Total"] = center_x
                        elif "CREDIT" in txt:
                            columns_x["Credit Note"] = center_x
                    break
            
            # Fallback coordinate center anchors if page header fails to bind
            if "Qty Sold" not in columns_x:
                columns_x = {
                    "Qty Sold": 340, "Invoice": 410, "Cash Sales": 480,
                    "Debit Note": 550, "Total": 630, "Credit Note": 700
                }
            
            # 3. Parse Data Rows
            for line in lines:
                if not line or len(line) < 3: 
                    continue
                
                line_text_upper = " ".join([w['text'].upper() for w in line])
                
                # Filter out system header text block descriptions and page summary metrics
                if any(k in line_text_upper for k in ["PRODUCT SALES REPORT", "PAGE", "PRINTED ON", "CODE DESCRIPTION", "SUMMARY", "QTY SOLD", "GRAND TOTAL", "SUBTOTAL"]):
                    continue
                if "TOTAL" in line_text_upper:
                    continue
                
                # Product entries always sit flush against the left boundary grid margin
                if line[0]['x0'] < 60:
                    product_code = line[0]['text'].strip()
                    
                    # Split descriptive text details from financial figures using column boundary limits
                    qty_sold_center = columns_x.get("Qty Sold", 340)
                    text_end_threshold = qty_sold_center - 35
                    
                    text_tokens = [w for w in line[1:] if w['x1'] < text_end_threshold]
                    num_tokens = [w for w in line[1:] if w['x1'] >= text_end_threshold]
                    
                    if not text_tokens:
                        continue
                        
                    # Last token in text boundary area is always the U/M column (e.g. PKT, KG, BOX)
                    um = text_tokens[-1]['text'].strip()
                    # Remaining intermediate tokens form the complete description line layout
                    product_description = " ".join([w['text'] for w in text_tokens[:-1]]).strip()
                    
                    # Initialize clean data map row structure
                    row_metrics = {
                        "Qty Sold": 0.0, "Invoice": 0.0, "Cash Sales": 0.0,
                        "Debit Note": 0.0, "Total": 0.0, "Credit Note": 0.0
                    }
                    
                    # Map numerical figures to their exact columns via coordinate proximity mapping
                    for w in num_tokens:
                        token_clean = w['text'].replace(',', '').strip()
                        if token_clean.startswith('(') and token_clean.endswith(')'):
                            token_clean = "-" + token_clean[1:-1]
                        if token_clean.endswith('.'):
                            token_clean = token_clean[:-1]
                            
                        try:
                            val = float(token_clean)
                            w_center = (w['x0'] + w['x1']) / 2
                            
                            # Match against closest visual column center position
                            financial_keys = ["Qty Sold", "Invoice", "Cash Sales", "Debit Note", "Total", "Credit Note"]
                            best_col = min(financial_keys, key=lambda k: abs(columns_x[k] - w_center))
                            
                            if abs(columns_x[best_col] - w_center) < 45:
                                row_metrics[best_col] = val
                        except ValueError:
                            pass
                    
                    all_products.append({
                        "Source File": source_file_name,
                        "From Date": from_date_global,
                        "Product Code": product_code,
                        "Description": product_description,
                        "U/M": um,
                        "Qty Sold": row_metrics["Qty Sold"],
                        "Invoice": row_metrics["Invoice"],
                        "Cash Sales": row_metrics["Cash Sales"],
                        "Debit Note": row_metrics["Debit Note"],
                        "Total": row_metrics["Total"],
                        "Credit Note": row_metrics["Credit Note"]
                    })
                    
    df = pd.DataFrame(all_products)
    if df.empty:
        return pd.DataFrame(columns=["Source File", "From Date", "Product Code", "Description", "U/M", "Qty Sold", "Invoice", "Cash Sales", "Debit Note", "Total", "Credit Note"])
        
    # Aggregate to seamlessly group entries split across page breaks
    df_grouped = df.groupby(
        ['Source File', 'From Date', 'Product Code', 'Description', 'U/M'], as_index=False
    )[['Qty Sold', 'Invoice', 'Cash Sales', 'Debit Note', 'Total', 'Credit Note']].sum()
    
    # Return columns in requested exact layout structure format
    final_columns = ["Source File", "From Date", "Product Code", "Description", "U/M", "Qty Sold", "Invoice", "Cash Sales", "Debit Note", "Total", "Credit Note"]
    return df_grouped[final_columns]


# --- ADVANCED EXCEL EXPORT ---
def export_to_excel_perfect_streamlit(df):
    """Saves the flat DataFrame to a beautifully formatted grid Excel sheet."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    
    df.to_excel(writer, sheet_name='Sales Report', index=False)
    
    workbook = writer.book
    worksheet = writer.sheets['Sales Report']
    
    # Custom cells configurations
    format_qty = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_val = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_text = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
    format_center = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
    format_header = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    
    # Overwrite headers with a clean gray filled background look
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, format_header)
    
    # Set explicit structured width sizes matching column contents
    worksheet.set_column('A:A', 35, format_text)    # Source File
    worksheet.set_column('B:B', 38, format_center)  # From Date [01/05/2026] To [31/05/2026]
    worksheet.set_column('C:C', 18, format_center)  # Product Code
    worksheet.set_column('D:D', 45, format_text)    # Description
    worksheet.set_column('E:E', 10, format_center)  # U/M
    worksheet.set_column('F:F', 14, format_qty)     # Qty Sold
    worksheet.set_column('G:G', 14, format_val)     # Invoice
    worksheet.set_column('H:H', 14, format_val)     # Cash Sales
    worksheet.set_column('I:I', 14, format_val)     # Debit Note
    worksheet.set_column('J:J', 14, format_val)     # Total
    worksheet.set_column('K:K', 14, format_val)     # Credit Note
    
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
    worksheet.freeze_panes(1, 0) 
    
    writer.close()
    output.seek(0)
    return output
