import pdfplumber
import pandas as pd
import re
from io import BytesIO

def process_zenxin_sales_report(pdf_path_or_bytes, source_file_name="Unknown"):
    all_products = []
    global_aligns = []
    report_type = 6 
    extracted_year = "YYYY" 
    
    if isinstance(pdf_path_or_bytes, bytes):
        pdf_file = BytesIO(pdf_path_or_bytes)
    else:
        pdf_file = pdf_path_or_bytes

    with pdfplumber.open(pdf_file) as pdf:
        current_category = "Uncategorized"
        
        for page in pdf.pages:
            words = page.extract_words()
            if not words: continue
            
            # 1. Group individual words into horizontal lines
            words.sort(key=lambda w: w['top'])
            lines = []
            current_line = []
            current_top = None
            
            for w in words:
                if current_top is None:
                    current_top = w['top']
                    current_line.append(w)
                elif abs(w['top'] - current_top) < 6:  
                    current_line.append(w)
                else:
                    lines.append(current_line)
                    current_line = [w]
                    current_top = w['top']
            if current_line:
                lines.append(current_line)
                
            for line in lines:
                line.sort(key=lambda w: w['x0'])
                
            # 2. Map out physical X-coordinates using RIGHT EDGES
            page_aligns = []
            for line in lines:
                qty_vals = [w for w in line if w['text'].lower() in ['qty', 'value']]
                if len(qty_vals) >= 14:
                    pts = [w['x1'] for w in qty_vals[-14:]]
                    if pts[-1] - pts[0] > 300: 
                        page_aligns = pts
                        break
                        
            if page_aligns:
                global_aligns = page_aligns
            aligns = global_aligns
            
            last_product_open = False 
            
            # 3. Process every line on the page
            for line in lines:
                if not line: continue
                
                full_text = " ".join([w['text'].upper() for w in line])
                
                # --- EXTRACT THE YEAR ---
                if "(FROM" in full_text and "TO" in full_text:
                    year_match = re.search(r'FROM\s+[A-Z]{3}-(\d{4})', full_text)
                    if year_match:
                        extracted_year = year_match.group(1)
                
                if "VIEW 12 MONTHS" in full_text: 
                    report_type = 12
                    last_product_open = False; continue
                if "VIEW 6 MONTHS" in full_text: 
                    report_type = 6
                    last_product_open = False; continue
                
                first_word = line[0]['text']
                first_word_x0 = line[0]['x0'] 
                
                line_has_data = False
                if aligns:
                    for w in line[1:]:
                        if w['x1'] > aligns[0] - 80:
                            text = w['text'].replace(',', '').strip()
                            if text.startswith('(') and text.endswith(')'): text = text[1:-1]
                            try: 
                                float(text)
                                line_has_data = True
                                break
                            except ValueError: 
                                pass
                                
                is_far_left = first_word_x0 < 50
                
                # --- STRICT SKIP RULES ---
                if full_text.count("QTY") >= 2 and full_text.count("VALUE") >= 2: 
                    last_product_open = False; continue
                if "GROUP TOTAL" in full_text or "GRAND TOTAL" in full_text or "PRINTED ON" in full_text: 
                    last_product_open = False; continue
                if "PRODUCT CODE" in full_text and "DESCRIPTION" in full_text: 
                    last_product_open = False; continue
                if "ZENXIN" in full_text and "AGRI" in full_text: 
                    last_product_open = False; continue
                if "PRODUCT SALES REPORT" in full_text: 
                    last_product_open = False; continue
                if "PAGE" in full_text and len(line) <= 2: 
                    last_product_open = False; continue
                if "(FROM" in full_text and "TO" in full_text: 
                    last_product_open = False; continue 
                if "MONTHS BY BOTH" in full_text: 
                    last_product_open = False; continue
                if not is_far_left and any(x in full_text for x in ["TOTAL", "SUBTOTAL", "SUB-TOTAL"]):
                    last_product_open = False; continue
                
                # --- CATEGORY DETECTION ---
                is_category = False
                if is_far_left and first_word.isdigit() and len(first_word) <= 4 and not line_has_data:
                    is_category = True
                    
                if is_category:
                    cat_desc = ""
                    if len(line) >= 2:
                        cat_desc = " ".join([w['text'] for w in line[1:]]).strip()
                    
                    current_category = (cat_desc if cat_desc else first_word).title()
                    
                    all_products.append({
                        "IsCategory": True,
                        "Code": first_word,
                        "Desc": cat_desc,
                        "Numbers": [None] * 26, 
                        "HasNumbers": False,
                        "Category": current_category
                    })
                    last_product_open = False 
                    continue
                
                # --- PRIMARY PRODUCT LINE ---
                is_product = False
                if is_far_left and not is_category:
                    is_product = True
                    
                if is_product:
                    last_product_open = True  
                    code = first_word
                    desc_words = []
                    nums = [0.0] * 26  
                    has_numbers = False 

                    for w in line[1:]:
                        text = w['text'].replace(',', '').strip()
                        w_align = w['x1'] 
                        is_num = False
                        val = 0.0
                        
                        if text.startswith('(') and text.endswith(')'):
                            try: val, is_num = -float(text[1:-1]), True
                            except ValueError: pass
                        else:
                            try: val, is_num = float(text), True
                            except ValueError: pass
                            
                        if is_num and aligns and w_align > (aligns[0] - 80):
                            best_idx = min(range(14), key=lambda i: abs(aligns[i] - w_align))
                            if abs(aligns[best_idx] - w_align) < 45:
                                has_numbers = True 
                                if report_type == 6:
                                    if best_idx < 12: nums[best_idx] = val
                                    else:             nums[24 + (best_idx - 12)] = val
                                else: 
                                    if best_idx < 12: nums[best_idx] = val
                        else:
                            desc_words.append(w['text'])
                            
                    all_products.append({
                        "IsCategory": False,
                        "Code": code, "Desc": " ".join(desc_words), 
                        "Numbers": nums, "HasNumbers": has_numbers,
                        "Category": current_category
                    })
                        
                # --> SECONDARY ROW (Data / Description Wraps)
                else:
                    if all_products and aligns and last_product_open:
                        wrap_words = []
                        for w in line:
                            text = w['text'].replace(',', '').strip()
                            w_align = w['x1']
                            is_num = False
                            val = 0.0
                            
                            if text.startswith('(') and text.endswith(')'):
                                try: val, is_num = -float(text[1:-1]), True
                                except ValueError: pass
                            else:
                                try: val, is_num = float(text), True
                                except ValueError: pass
                                
                            if is_num and report_type == 12 and w_align > (aligns[0] - 80):
                                best_idx = min(range(14), key=lambda i: abs(aligns[i] - w_align))
                                if abs(aligns[best_idx] - w_align) < 45:
                                    all_products[-1]["Numbers"][12 + best_idx] = val
                                    all_products[-1]["HasNumbers"] = True
                            elif not is_num and w['x1'] < aligns[0] - 15:
                                wrap_words.append(w['text'])
                        
                        if wrap_words:
                            all_products[-1]["Desc"] += " " + " ".join(wrap_words)

    # 4. Compile cleanly into a Flat DataFrame Layout
    records = []
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    for p in all_products:
        if p["IsCategory"] or not p["HasNumbers"]:
            continue
            
        cat = p.get("Category", "Uncategorized")
        code = p.get("Code", "")
        desc = p.get("Desc", "")
        nums = p["Numbers"]
        
        for i, m in enumerate(months):
            qty = nums[i*2]
            val = nums[i*2 + 1]
            
            # Only append if there is actual numerical data
            if pd.notna(qty) and pd.notna(val) and (qty != 0 or val != 0):
                records.append({
                    "Source File": source_file_name,
                    "Category": cat,
                    "Product Code": code,
                    "Description": desc,
                    "Year": extracted_year,
                    "Month Name": m, # Used temporarily for sorting
                    "Month": f"{m}-{str(extracted_year)[-2:]}",
                    "Qty": qty,
                    "Val": val
                })
                
    df_flat = pd.DataFrame(records)
    
    if df_flat.empty:
        return pd.DataFrame() 
        
    # Aggregate data logically (merges duplicate rows if any exist)
    df_grouped = df_flat.groupby(
        ['Source File', 'Category', 'Product Code', 'Description', 'Year', 'Month Name', 'Month']
    )[['Qty', 'Val']].sum().reset_index()
    
    # Sort chronologically by Month
    month_map = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, 
                 "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    
    df_grouped['Temp_Month_Num'] = df_grouped['Month Name'].map(month_map)
    df_grouped.sort_values(by=['Source File', 'Category', 'Product Code', 'Year', 'Temp_Month_Num'], inplace=True)
    
    # Drop the temporary sorting columns before returning
    df_grouped.drop(columns=['Temp_Month_Num', 'Month Name'], inplace=True)
    
    return df_grouped


# --- ADVANCED EXCEL EXPORT (Updated for Flat Layout) ---
def export_to_excel_perfect_streamlit(df):
    """Saves the Flat DataFrame to a beautifully formatted Excel file."""
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    
    # Standard output without index
    df.to_excel(writer, sheet_name='Sales Report', index=False)
    
    workbook = writer.book
    worksheet = writer.sheets['Sales Report']
    
    # Styling
    format_qty = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_val = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
    format_text = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
    format_center = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
    format_header = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    
    # Write custom headers
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, format_header)
    
    # Set explicit column widths
    worksheet.set_column('A:A', 35, format_text)    # Source File
    worksheet.set_column('B:B', 20, format_text)    # Category
    worksheet.set_column('C:C', 18, format_center)  # Product Code
    worksheet.set_column('D:D', 45, format_text)    # Description
    worksheet.set_column('E:E', 10, format_center)  # Year
    worksheet.set_column('F:F', 12, format_center)  # Month
    worksheet.set_column('G:G', 12, format_qty)     # Qty
    worksheet.set_column('H:H', 14, format_val)     # Val
    
    # Add auto-filter to the top row and freeze the top row for easy reading
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
    worksheet.freeze_panes(1, 0) 
    
    writer.close()
    
    output.seek(0)
    return output
