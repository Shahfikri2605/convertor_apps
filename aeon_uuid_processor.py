import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO

def extract_aeon_uuid_raw_data(pdf_bytes, filename):
    data = []
    
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text: continue
            
            lines = text.split('\n')
            
            # Reset page-specific variables
            current_store_name = None
            current_store_code = None
            current_doc_number = None
            current_uuid = None
            current_date = None
            page_doc_type = "INVOICE" 
            
            # --- 1. HEADER & DOC TYPE DETECTION ---
            for line in lines[:40]: 
                line_upper = line.upper()
                line_nospaces = line.replace(" ", "").upper()

                if "CREDITNOTE" in line_nospaces or "CREDIT NOTE" in line_upper:
                    page_doc_type = "CREDIT NOTE"

                elif "CONFIRMATIONFORDEDUCTION" in line_nospaces or "CONFIRMATION FOR DEDUCTION" in line_upper:
                    page_doc_type ="DEDUCTION"
                
                if "STORECODE" in line_nospaces:
                    code_match = re.search(r"STORECODE[:\.]?(\d+)", line_nospaces)
                    if code_match:
                        current_store_code = code_match.group(1)
                
                if "STORENAME" in line_nospaces:
                    name_match = re.search(r"(Store\s*Name\s*[:\.]?\s*)(.+)", line, re.IGNORECASE)
                    if name_match:
                        raw_value = name_match.group(2)
                        clean_name = re.split(r"ST\s*Rate|ST\s*Rate", raw_value, flags=re.IGNORECASE)[0]
                        current_store_name = clean_name.strip()

                if any(x in line_nospaces for x in ["INVOICENO", "CREDITNOTENO","DOCUMENTNO"]):
                    doc_match = re.search(r"(?:INVOICENO|CREDITNOTENO|DOCUMENTNO)[\.:]*(\S+)", line_nospaces)
                    if doc_match:
                        raw_val = doc_match.group(1)
                        clean_num = re.split(r"DATE", raw_val)[0]
                        current_doc_number = clean_num.strip()

                # --- EXTRACT LHDN UUID ---
                if "LHDNUUID" in line_nospaces:
                    uuid_match = re.search(r"LHDNUUID[:\s]*(\w+)", line_nospaces)
                    if uuid_match:
                        current_uuid = uuid_match.group(1)

                # --- EXTRACT INVOICE DATE ---
                if "DATE" in line_nospaces or re.search(r"\b\d{2}/\d{2}/\d{4}\b", line):
                    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                    if date_match and not current_date:
                        current_date = date_match.group(1)

            if not current_store_name:
                continue

            # --- 2. EXTRACT ITEMS ---
            for line in lines:
                line_upper = line.upper()
                
                # --- A. CAPTURE "INVOICE TOTAL" (For Delivery Logic) ---
                if "INCLUDE" in line_upper and "TAX" in line_upper and "TOTAL" in line_upper:
                    matches = re.findall(r"([\d,]+\.\d{2})", line)
                    if matches:
                        values = [float(m.replace(',', '')) for m in matches]
                        amount = max(values)
                        
                        data.append({
                            "DOC_TYPE": page_doc_type,
                            "LOCATION": current_store_name,
                            "CODE": current_store_code,
                            "INVOICE_NO": current_doc_number,
                            "DATE": current_date,
                            "LHDN_UUID": current_uuid,
                            "DESCRIPTION": "INVOICE_TOTAL_CANDIDATE",
                            "MARGIN": 0.0,
                            "AMOUNT": amount,
                            "SOURCE_FILE": filename
                        })
                        continue

                # Skip Header/Footer garbage
                if any(x in line_upper for x in ["INVOICE", "CREDIT NOTE", "DATE :", "PAGE", "SUPPLIER", "AEON CO"]):
                    continue

                margin = 0.0
                amount = 0.0
                description = ""

                # --- B. STANDARD ITEMS ---
                if re.search(r"\b(20|23)\s+[\d\.,]+\s+([\d,]+\.\d{2})", line):
                    strict_match = re.search(r"\b(20|23)\s+[\d\.,]+\s+([\d,]+\.\d{2})", line)
                    margin = float(strict_match.group(1))
                    amount = float(strict_match.group(2).replace(',', ''))
                    description = line.split(strict_match.group(0))[0].strip().upper()

                # --- C. FALLBACK ---
                else:
                    amount_match = re.search(r"(?:RM\s?)?([\d,]+\.\d{2})\s*$", line)
                    if amount_match:
                        try:
                            amount = float(amount_match.group(1).replace(',', ''))
                            description = line.replace(amount_match.group(0), "").strip().upper()
                        except:
                            continue
                    else:
                        continue 

                description = " ".join(description.split())
                
                is_wanted = "DELIVERY" in description or "CHARGE" in description or "TAX" in description or "SST" in description
                if "TOTAL" in description and not is_wanted:
                    continue

                data.append({
                    "DOC_TYPE": page_doc_type,
                    "LOCATION": current_store_name,
                    "CODE": current_store_code,
                    "INVOICE_NO": current_doc_number,
                    "DATE": current_date,
                    "LHDN_UUID": current_uuid,
                    "DESCRIPTION": description,
                    "MARGIN": margin,
                    "AMOUNT": amount,
                    "SOURCE_FILE": filename
                })

    return pd.DataFrame(data)

def generate_aeon_excel(df, file_summary):
    if df.empty: return None
    
    def is_deduction(row):
        desc = row['DESCRIPTION']
        return row['DOC_TYPE'] == 'DEDUCTION' and "TOTAL" not in desc and "TAX" not in desc

    def is_autopay(row):
        return "AUTOPAY" in row['DESCRIPTION']

    def is_5213(row):
        desc = row['DESCRIPTION']
        has_dept = "DEPARTMENT" in desc or "DEPT" in desc
        return "5213" in desc and has_dept and "DELIVERY" not in desc and not is_autopay(row)

    def is_5201_5202(row):
        desc = row['DESCRIPTION']
        has_dept = "DEPARTMENT" in desc or "DEPT" in desc
        if not has_dept: return False
        if "5201" not in desc and "5202" not in desc: return False
        if is_autopay(row): return False
        if "DELIVERY" in desc: return False 
        return True

    def is_23_vege(row): return row['MARGIN'] == 23.0
    def is_20_dry(row): return row['MARGIN'] == 20.0
    def is_delivery_indicator(desc):
        return "DELIVERY" in desc or "DC CHARGE" in desc or "TRANSPORT" in desc
        
    # --- NEW DETECTOR FOR PROMOTIONAL SERVICES ---
    def is_promo_adv(row):
        desc = row['DESCRIPTION']
        return "PROMOTIONAL" in desc or "ADVERTISING" in desc

    # --- 2. CALCULATE CHARGES ---
    df['Delivery charges'] = 0.0

    for (location, invoice), group in df.groupby(['LOCATION', 'INVOICE_NO']):
        is_delivery_invoice = group['DESCRIPTION'].apply(is_delivery_indicator).any()
        total_row_idx = group[group['DESCRIPTION'] == "INVOICE_TOTAL_CANDIDATE"].index
        if is_delivery_invoice:
            if not total_row_idx.empty:
                grand_total_amt = df.loc[total_row_idx[0], 'AMOUNT']
                df.loc[total_row_idx, 'Delivery charges'] = grand_total_amt
                other_rows = group.index.difference(total_row_idx)
                df.loc[other_rows, 'AMOUNT'] = 0
            else:
                parts_mask = group['DESCRIPTION'].apply(lambda x: is_delivery_indicator(x) or "TAX" in x or "SST" in x)
                df.loc[group[parts_mask].index, 'Delivery charges'] = df.loc[group[parts_mask].index, 'AMOUNT']

    df['AUTOPAY'] = df.apply(lambda x: x['AMOUNT'] if is_autopay(x) else 0, axis=1)
    df['Confirmation Deduction'] = df.apply(lambda x: x['AMOUNT'] if is_deduction(x) else 0, axis=1)
    df['23% Vege'] = df.apply(lambda x: x['AMOUNT'] if is_23_vege(x) else 0, axis=1)
    df['5213'] = df.apply(lambda x: x['AMOUNT'] if is_5213(x) else 0, axis=1)
    df['5201/5202'] = df.apply(lambda x: x['AMOUNT'] if is_5201_5202(x) else 0, axis=1)
    df['20% Dry Food'] = df.apply(lambda x: x['AMOUNT'] if is_20_dry(x) else 0, axis=1)
    # Map the amount to the new column
    df['Promo/Adv Services'] = df.apply(lambda x: x['AMOUNT'] if is_promo_adv(x) else 0, axis=1)

    # --- 3. AGGREGATE BY INVOICE DETAILS ---
    agg_rules = {
        'AUTOPAY': 'sum',
        '23% Vege': 'sum',
        '5213': 'sum',
        'Delivery charges': 'sum',
        '5201/5202': 'sum',
        '20% Dry Food': 'sum',
        'Confirmation Deduction': 'sum',
        'Promo/Adv Services': 'sum'  # Added to aggregation
    }

    # Added 'Promo/Adv Services' to the output column order layout
    cols_order = [
        'LOCATION', 'CODE', 'INVOICE_NO', 'DATE', 'LHDN_UUID', 
        'AUTOPAY', '23% Vege', '5213', 'Delivery charges', 
        '5201/5202', '20% Dry Food', 'Confirmation Deduction', 'Promo/Adv Services'
    ]

    groupby_keys = ['LOCATION', 'CODE', 'INVOICE_NO', 'DATE', 'LHDN_UUID']

    df_inv = df[df['DOC_TYPE'].isin(['INVOICE', 'DEDUCTION'])]
    final_inv = pd.DataFrame()
    if not df_inv.empty:
        final_inv = df_inv.groupby(groupby_keys, dropna=False).agg(agg_rules).reset_index()[cols_order]

    df_cn = df[df['DOC_TYPE'] == 'CREDIT NOTE']
    final_cn = pd.DataFrame()
    if not df_cn.empty:
        final_cn = df_cn.groupby(groupby_keys, dropna=False).agg(agg_rules).reset_index()[cols_order]

    # --- 4. WRITE TO MEMORY (BytesIO) ---
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if not final_inv.empty:
            final_inv.to_excel(writer, sheet_name='INVOICE', index=False)
        if not final_cn.empty:
            final_cn.to_excel(writer, sheet_name='CREDIT NOTE', index=False)
        
        # Summary Sheet
        if file_summary:
            summary_rows = []
            for fname, count in file_summary:
                if isinstance(count, (int, float)) and 'SOURCE_FILE' in df.columns:
                    file_df = df[df['SOURCE_FILE'] == fname]
                    total_amt = (
                        file_df['AUTOPAY'].sum() + file_df['23% Vege'].sum() +
                        file_df['5213'].sum() + file_df['Delivery charges'].sum() +
                        file_df['5201/5202'].sum() + file_df['20% Dry Food'].sum() +
                        file_df['Confirmation Deduction'].sum() + file_df['Promo/Adv Services'].sum()
                    )
                else:
                    total_amt = ''
                summary_rows.append((fname, count, total_amt))
            
            pd.DataFrame(summary_rows, columns=["FILENAME", "EXTRACTED_ITEMS", "TOTAL_AMOUNT"]).to_excel(writer, sheet_name='SUMMARY', index=False)
            
    return output, final_inv
