import pdfplumber
import re
import os
import tempfile

def process_tfp_pdf(pdf_bytes, filename):
    """
    Extracts TFP/Global Report data from PDF bytes.
    Returns a list of dictionaries (rows).
    """
    rows = []
    temp_path = None
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path=tmp.name
        # Open the PDF from bytes (Streamlit upload)
        with pdfplumber.open(temp_path) as pdf:
            
            # STATE VARIABLES
            last_store = "Unknown"
            last_dept = "Unknown"
            last_sku = ""
            last_desc = ""
            last_item_no = ""

            total_pages = len(pdf.pages)
            print(f"Processing {total_pages} pages in {filename}...")
            for i, page in enumerate(pdf.pages):
                if i % 50 == 0:
                    print (f"..Scanning Page {i}/{total_pages}")
                table = page.extract_table()
                if not table:
                    continue

                for row in table:
                    # 1. Basic Cleaning
                    if not row or len(row) < 15:
                        continue
                    
                    # Convert all cells to string
                    raw_row = [str(cell).strip() if cell else "" for cell in row]
                    row_full_text = " ".join(raw_row).lower().replace('\n', ' ')

                    # --- FILTER 1: Skip Headers ---
                    if "vendor" in raw_row[0].lower() or "store" in raw_row[1].lower():
                        continue

                    # --- FILTER 2: Exclude Summary Rows ---
                    is_summary_row = False
                    for col_idx in range(5): 
                        if col_idx < len(raw_row):
                            cell_text = raw_row[col_idx].lower().replace('\n', ' ').strip()
                            if cell_text.startswith("total"):
                                is_summary_row = True
                                break
                    
                    if is_summary_row:
                        continue
                    
                    # Extra safety check
                    if "total" in row_full_text and "bbt" in row_full_text:
                        continue

                    # 2. FILL DOWN LOGIC (Store & Dept)
                    store_val = raw_row[1].replace('\n', ' ').strip()
                    if store_val:
                        last_store = store_val
                    
                    dept_val = raw_row[2].replace('\n', ' ').strip()
                    if dept_val:
                        last_dept = dept_val 

                    # 3. SKU & DESCRIPTION LOGIC
                    raw_desc_cell = raw_row[4]
                    item_val = raw_desc_cell.replace('\n', ' ').strip()
                    if item_val:
                        last_item_no = item_val
                    
                    # Search for SKU (7 digits)
                    found_skus = re.findall(r"(\d{7,})", raw_desc_cell)
                    
                    if found_skus:
                        primary_sku = found_skus[0]
                        clean_desc = raw_desc_cell.replace('\n', ' ').replace(primary_sku, '').strip()
                        last_sku = primary_sku
                        last_desc = clean_desc
                    
                    # 4. PROCESS QUANTITIES (Split Merged Lines)
                    # Indices based on your script: Qty=5, Total=15, Cost=16
                    qty_cell = raw_row[5].replace(',', '')
                    total_cell = raw_row[15].replace(',', '')
                    cost_cell = raw_row[16].replace(',', '')

                    qty_values = qty_cell.split('\n')
                    total_values = total_cell.split('\n')
                    cost_values = cost_cell.split('\n')

                    for idx, q_val in enumerate(qty_values):
                        q_str = q_val.strip()
                        if not q_str: 
                            continue 
                        
                        try:
                            qty = float(q_str)
                        except ValueError:
                            continue 

                        try:
                            t_str = total_values[idx].strip() if idx < len(total_values) else "0"
                            total_exc = float(t_str) if t_str else 0.0
                        except ValueError:
                            total_exc = 0.0

                        try:
                            c_str = cost_values[idx].strip() if idx < len(cost_values) else "0"
                            cost_exc = float(c_str) if c_str else 0.0
                        except ValueError:
                            cost_exc = 0.0

                        # DECIDE SKU
                        if found_skus and idx < len(found_skus):
                            current_sku = found_skus[idx]
                            current_desc = last_desc 
                        else:
                            current_sku = last_sku
                            current_desc = last_desc

                        if not current_sku:
                            continue

                        rows.append({
                            "Source File": filename,
                            "Store": last_store,
                            "Dept": last_dept,
                            "SKU No": current_sku,
                            "Description": current_desc,
                            "Item No/SKU": last_item_no,
                            "Qty": qty,
                            "Total Excl Tax": total_exc,
                            "Cost Excl Tax": cost_exc
                        })
                page.flush_cache()                
                        
        return rows

    except Exception as e:
        print(f"TFP Error: {e}")
        return []
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass
