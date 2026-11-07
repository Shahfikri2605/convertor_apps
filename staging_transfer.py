import pandas as pd
from io import BytesIO

def parse_location_code(code_val):
    if pd.isna(code_val):
        return ""
    code_str = str(code_val).strip()
    if code_str.startswith("RETAIL-"):
        parts = code_str.split("-")
        if len(parts) >= 2:
            return parts[1]
    if "-" in code_str:
        parts = code_str.split("-")
        return parts[1]
    return code_str

def convert_sk_transfer_to_shah_stock(file_input, start_seq=1):
    """
    Reads 'All' sheet from 'SK Transfer to supermarket 202610.xlsx'
    and generates an Excel workbook in 'Shah stock .xlsx' format:
    - Document No. -> Auto running CON26-0001, CON26-0002...
    - External Document No. -> Preserved at the last column.
    """
    if isinstance(file_input, bytes):
        file_input = BytesIO(file_input)
        
    excel_obj = pd.ExcelFile(file_input)
    sheet_name = 'All' if 'All' in excel_obj.sheet_names else excel_obj.sheet_names[0]
    df_src = pd.read_excel(excel_obj, sheet_name=sheet_name)
    
    # Normalize column names (remove newlines and extra spaces)
    df_src.columns = [col.split('\n')[0].strip() for col in df_src.columns]
    
    # Build unique document mapping for auto-running sequence: CON26-0001, CON26-0002...
    doc_mapping = {}
    current_counter = start_seq
    for doc in df_src['External Document No.'].dropna():
        doc_str = str(doc).strip()
        if doc_str and doc_str not in doc_mapping:
            doc_mapping[doc_str] = f"CON26-{current_counter:04d}"
            current_counter += 1
            
    journal_rows = []
    
    for _, row in df_src.iterrows():
        post_date = pd.to_datetime(row.get('Posting Date'), errors='coerce')
        orig_doc_no = str(row.get('External Document No.', '')).strip()
        
        # Auto-assigned CON26-XXXX format
        running_doc_no = doc_mapping.get(orig_doc_no, f"CON26-{current_counter:04d}")
        
        item_no = row.get('Item No.', '')
        if pd.notna(item_no) and isinstance(item_no, (int, float)):
            item_no = str(int(item_no))
        else:
            item_no = str(item_no).strip()
            
        desc = str(row.get('USOFT product description', '')).strip()
        uom = str(row.get('Unit Of Measure Code', '')).strip()
        
        try:
            qty = float(str(row.get('Quantity', 0)).replace(',', ''))
        except (ValueError, TypeError):
            qty = 0.0
            
        from_loc_raw = row.get('Transfer-from Code', '')
        to_loc_raw = row.get('Transfer-to Code', '')
        
        from_loc = parse_location_code(from_loc_raw)
        to_loc = parse_location_code(to_loc_raw)
        
        bunit = row.get('Businessunit Code', None)
        project = row.get('Project Code', None)
        
        # 1. MOVE IN: Positive Adjmt.
        journal_rows.append({
            'Posting Date': post_date,
            'Entry Type': 'Positive Adjmt.',
            'Document No.': running_doc_no,
            'Item No.': item_no,
            'Description': desc,
            'Location Code': to_loc,
            'Unit Price POS': 0,
            'Amount Inc GST POS': 0,
            'Quantity': qty,
            'Unit of Measure Code': uom,
            'Unit Amount': 0.0,
            'Amount': 0.0,
            'Discount Amount': 0,
            'Terminal Code': None,
            'Unit Cost': 0.0,
            'Shortcut Dimension 6 Code': None,
            'Applies-to Entry': 0,
            'Bin Code': None,
            'Businessunit Code': bunit if pd.notna(bunit) else None,
            'Project Code': project if pd.notna(project) else None,
            'Manufacturer Code': None,
            'External Document No.': orig_doc_no  # Added to the last column
        })
        
        # 2. MOVE OUT: Negative Adjmt.
        journal_rows.append({
            'Posting Date': post_date,
            'Entry Type': 'Negative Adjmt.',
            'Document No.': running_doc_no,
            'Item No.': item_no,
            'Description': desc,
            'Location Code': from_loc,
            'Unit Price POS': 0,
            'Amount Inc GST POS': 0,
            'Quantity': -qty,
            'Unit of Measure Code': uom,
            'Unit Amount': 0.0,
            'Amount': 0.0,
            'Discount Amount': 0,
            'Terminal Code': None,
            'Unit Cost': 0.0,
            'Shortcut Dimension 6 Code': None,
            'Applies-to Entry': 0,
            'Bin Code': None,
            'Businessunit Code': bunit if pd.notna(bunit) else None,
            'Project Code': project if pd.notna(project) else None,
            'Manufacturer Code': None,
            'External Document No.': orig_doc_no  # Added to the last column
        })

    df_journal = pd.DataFrame(journal_rows)
    
    # Build styled Excel matching Shah Stock layout
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        sheet_title = 'Edit - Item Journal - CONSIGN '
        workbook = writer.book
        worksheet = workbook.add_worksheet(sheet_title)
        writer.sheets[sheet_title] = worksheet
        
        # Format definitions
        title_fmt = workbook.add_format({'bold': True})
        hdr_fmt = workbook.add_format({'bold': True, 'border': 1, 'align': 'left', 'valign': 'vcenter'})
        date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd', 'align': 'center', 'valign': 'vcenter'})
        text_fmt = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
        center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
        num_fmt = workbook.add_format({'num_format': '#,##0.##', 'align': 'right', 'valign': 'vcenter'})
        curr_fmt = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter'})
        
        # Row 0: Business Central Banner
        worksheet.write(0, 0, 'Edit - Item Journal - CONSIGN ∙ Consignment Journal', title_fmt)
        
        # Row 1: Column Headers
        headers = list(df_journal.columns)
        for col_idx, col_name in enumerate(headers):
            worksheet.write(1, col_idx, col_name, hdr_fmt)
            
        # Rows 2+: Data
        for row_idx, record in enumerate(df_journal.to_dict(orient='records'), start=2):
            for col_idx, col_name in enumerate(headers):
                val = record[col_name]
                if pd.isna(val) or val is None:
                    continue
                elif col_name == 'Posting Date':
                    worksheet.write_datetime(row_idx, col_idx, val, date_fmt)
                elif col_name in ['Quantity']:
                    worksheet.write_number(row_idx, col_idx, val, num_fmt)
                elif col_name in ['Unit Amount', 'Amount', 'Unit Cost', 'Unit Price POS', 'Amount Inc GST POS', 'Discount Amount']:
                    worksheet.write_number(row_idx, col_idx, val, curr_fmt)
                elif col_name in ['Entry Type', 'Document No.', 'Location Code', 'Unit of Measure Code', 'Item No.']:
                    worksheet.write(row_idx, col_idx, str(val), center_fmt)
                else:
                    worksheet.write(row_idx, col_idx, str(val), text_fmt)
                    
        # Explicit Column Widths
        col_widths = {
            0: 14,  # Posting Date
            1: 16,  # Entry Type
            2: 15,  # Document No. (CON26-XXXX)
            3: 14,  # Item No.
            4: 40,  # Description
            5: 14,  # Location Code
            6: 14,  # Unit Price POS
            7: 18,  # Amount Inc GST POS
            8: 12,  # Quantity
            9: 20,  # Unit of Measure Code
            10: 14, # Unit Amount
            11: 14, # Amount
            12: 16, # Discount Amount
            13: 14, # Terminal Code
            14: 14, # Unit Cost
            15: 24, # Shortcut Dimension 6 Code
            16: 16, # Applies-to Entry
            17: 12, # Bin Code
            18: 18, # Businessunit Code
            19: 14, # Project Code
            20: 18, # Manufacturer Code
            21: 22  # External Document No. (TF2026...)
        }
        for col_idx, width in col_widths.items():
            worksheet.set_column(col_idx, col_idx, width)
            
        worksheet.autofilter(1, 0, len(df_journal) + 1, len(headers) - 1)
        worksheet.freeze_panes(2, 0)
        
    output.seek(0)
    return output, df_journal
