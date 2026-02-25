import pdfplumber
import pandas as pd
import re
import tempfile
import os
from io import BytesIO
from datetime import datetime

def parse_custom_date(date_str):
    """Converts '02DEC25' to '02/12/2025'"""
    try:
        # Parse DDMMMYY (e.g. 02DEC25)
        dt = datetime.strptime(date_str, "%d%b%y")
        return dt.strftime("%d/%m/%Y")
    except:
        return date_str

def extract_data_from_pdf(pdf_bytes):
    """Extracts transaction rows from a SINGLE Public Bank Payment Advice PDF."""
    rows = []
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        temp_path = tmp.name

    try:
        with pdfplumber.open(temp_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                
                for table in tables:
                    for row in table:
                        clean_row = [str(cell).replace('\n', ' ').strip() if cell else "" for cell in row]
                        
                        if len(clean_row) < 8:
                            continue
                            
                        date_str = clean_row[3]
                        if not re.match(r"\d{2}[A-Z]{3}\d{2}", date_str):
                            continue
                        
                        try:
                            date_val = parse_custom_date(date_str)
                            gross = float(clean_row[4].replace(',', ''))
                            comm = float(clean_row[5].replace(',', ''))
                            net = float(clean_row[7].replace(',', ''))
                            
                            rows.append({
                                "DATE": date_val,
                                "DESCRIPTION": "PUBLIC BANK CARD", 
                                "AMOUNT": gross,
                                "COMMISSION": comm,
                                "BANK": net
                            })
                        except ValueError:
                            continue 
                            
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
            
    return pd.DataFrame(rows)

def process_publicbank_files(uploaded_files, report_month, outlet_name, company_name, bank_account):
    """
    Main function: Combines MULTIPLE PDFs -> Sorts -> Formats into Excel.
    """
    all_dfs = []

    for file_obj in uploaded_files:
        try:
            print(f"Processing {file_obj.name}...")
            df = extract_data_from_pdf(file_obj.getvalue())
            if not df.empty:
                all_dfs.append(df)
        except Exception as e:
            print(f"Error reading {file_obj.name}: {e}")
            continue

    if not all_dfs:
        return None, None

    df_combined = pd.concat(all_dfs, ignore_index=True)
    
    df_combined['temp_date'] = pd.to_datetime(df_combined['DATE'], format="%d/%m/%Y", errors='coerce')
    df_combined = df_combined.sort_values(by='temp_date').drop(columns=['temp_date'])

    header_rows = [
        [None, None, None, None, None, None], 
        [None, None, None, None, None, None], 
        [None, company_name, None, None, None, None], 
        [None, bank_account, None, None, None, None], 
        [None, None, None, None, None, None], 
        [None, report_month, None, None, None, None], 
        [None, None, None, None, None, None], 
        [None, outlet_name, None, None, None, None], 
        [None, None, None, None, None, None], 
        [None, 'DATE', 'DESCRIPTION ', 'AMOUNT', 'COMMISSION ', 'BANK'], 
        [None, None, None, 'RM', 'RM', 'RM'] 
    ]
    
    data_values = df_combined.values.tolist()
    data_rows = [[None] + row for row in data_values]
    
    final_rows = header_rows + data_rows
    df_final = pd.DataFrame(final_rows)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_final.to_excel(writer, index=False, header=False, sheet_name='Sheet1')
        
        workbook = writer.book
        worksheet = writer.sheets['Sheet1']
        
        border_fmt = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
        bold_fmt = workbook.add_format({'bold': True})
        
        start_row = 9
        end_row = len(final_rows) - 1
        worksheet.conditional_format(start_row, 1, end_row, 5, {
            'type': 'no_errors', 'format': border_fmt
        })
        
        worksheet.write(2, 1, company_name, bold_fmt)
        worksheet.write(3, 1, bank_account, bold_fmt)
        worksheet.write(5, 1, report_month, bold_fmt)
        worksheet.write(7, 1, outlet_name, bold_fmt)
        
        worksheet.set_column('A:A', 2)
        worksheet.set_column('B:B', 15)
        worksheet.set_column('C:C', 25)
        worksheet.set_column('D:F', 15)
        
    return output, df_combined
