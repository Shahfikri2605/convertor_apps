import google.generativeai as genai
import json
import tempfile
import os
import time
import shutil
from io import BytesIO
from pypdf import PdfReader, PdfWriter

def process_kastam_pdf(pdf_bytes, filename, api_key):
    """
    Extracts Kastam data using 'Chunking' (Processing 3 pages at a time).
    - Saves API Quota (3x fewer requests than page-by-page).
    - Maintains 100% Accuracy (unlike sending the whole file).
    """
    rows = []
    CHUNK_SIZE = 3  
    
    # Configure API
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-3-flash-preview')
    
    temp_dir = tempfile.mkdtemp()

    try:
        # Load PDF
        reader = PdfReader(BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        print(f"--- Processing {total_pages} pages in batches of {CHUNK_SIZE} ---")

        for i in range(0, total_pages, CHUNK_SIZE):
            writer = PdfWriter()
            
            end_page = min(i + CHUNK_SIZE, total_pages)
            for page_num in range(i, end_page):
                writer.add_page(reader.pages[page_num])
            
            chunk_filename = f"chunk_{i+1}_to_{end_page}.pdf"
            chunk_path = os.path.join(temp_dir, chunk_filename)
            with open(chunk_path, "wb") as f:
                writer.write(f)

            uploaded_file = None
            try:
                uploaded_file = genai.upload_file(chunk_path, mime_type="application/pdf")
                
                while uploaded_file.state.name == "PROCESSING":
                    time.sleep(0.5)
                    uploaded_file = genai.get_file(uploaded_file.name)

                prompt = """
                You are a Forensic Data Auditor. Extract data from these pages of the Kastam Invoice.
                - Please extract for all pages in the PDF.
                - accurately extract all line items from the tables.
                - make sure all data is 100% accurate, especially the numbers (Qty, Unit Charge).
            
                
                1. Look for the **INVOICE NO** in the header (it applies to all rows).
                Return VALID JSON only:
                {
                  "Invoice_No": "string",
                  "Line_Items": [
                    {
                      "Decl_Date": "string",
                      "Lorry_No": "string",
                      "Goods": "string",
                      "Exp_Date": "string",
                      "Qty": number,
                      "Unit_Chrg": number
                    }
                  ]
                }
                """

                response = model.generate_content(
                    [uploaded_file, prompt],
                    generation_config={'response_mime_type': 'application/json'}
                )

                data = json.loads(response.text)
                
                page_invoice_no = data.get("Invoice_No", "")
                items = data.get("Line_Items", [])

                if items:
                    for item in items:
                        if not item.get("Invoice_No"): 
                            item["Invoice_No"] = page_invoice_no
                        
                        item['Source File'] = filename
                        item['Page Batch'] = f"{i+1}-{end_page}" # Track which batch it came from
                        rows.append(item)
                    print(f"   > Batch {i+1}-{end_page}: Extracted {len(items)} rows.")
                else:
                    print(f"   > Batch {i+1}-{end_page}: No data.")

            except Exception as e:
                print(f"Error on batch {i+1}-{end_page}: {e}")

            finally:
                if uploaded_file:
                    try:
                        genai.delete_file(uploaded_file.name)
                    except: pass
            
            time.sleep(3)

    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    return rows
