import pandas as pd
import json
import tempfile
import os
import time
import google.generativeai as genai

def upload_to_gemini(file_path, mime_type="application/pdf"):
    """Uploads the file to Gemini and waits for processing."""
    file = genai.upload_file(file_path, mime_type=mime_type)
    
    # Wait for file to be ready
    while file.state.name == "PROCESSING":
        time.sleep(1)
        file = genai.get_file(file.name)
        
    if file.state.name != "ACTIVE":
        raise Exception(f"Gemini File Error: {file.state.name}")
    
    return file

def process_jaya_pdf(pdf_bytes, filename, api_key):
    """
    Extracts Jaya Grocer Consignment Report (ZA02).
    - Repairs StkNo vs Description merge.
    - Calculates totals manually in Python.
    """
    rows = []
    
    # Configure API
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash") 
    
    temp_path = None
    uploaded_file_ref = None

    try:
        # 1. Save Streamlit bytes to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        # 2. Upload to Gemini
        uploaded_file_ref = upload_to_gemini(temp_path)

        # 3. Prompt (Your Exact Logic)
        prompt = """You are a Forensic Data Auditor. Extract data from this Consignment Report (ZA02).
        - Please extract for all pages in the PDF.
        - Please extract data with 100% accuracy.

        ### REPAIR STRATEGY (Execute in order):
        1. **Fix Column Merge (Description vs StkNo)**:
           - The first column has the Description and Stock Number mixed.
           - **StkNo Rule**: Find the **6-digit number**. Extract this as 'StkNo'.
           - **Description Rule**: Everything else in that column is the 'Description'.

        ### SCHEMA OUTPUT:
        Return strictly valid JSON.
        {
            "Location": "string",
            "Invoice Date": "string",
            "Items": [
                {
                    "StkNo": "string",
                    "Description": "string",
                    "Qty": number,
                    "NSales": number,
                    "U_Retail": number
                }
            ]
        }
        """

        response = model.generate_content(
            [uploaded_file_ref, prompt],
            generation_config={"response_mime_type": "application/json"}
        )

        # 4. Parse JSON
        raw_json = response.text
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            clean_json = raw_json.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
        
        if isinstance(data, list):
            if len(data) > 0 and isinstance(data[0], dict):
                data = data[0]
            else:
                print("Error: AI returned an empty list or invalid format.")
                return rows

        # 5. Process Data (Python Logic)
        location = data.get("Location", "")
        inv_date = data.get("Invoice Date", "")
        items = data.get("Items", [])

        if items:
            for item in items:
                # Format StkNo (Pad with zeros)
                stk_val = str(item.get("StkNo", "")).strip()
                if stk_val.isdigit() and len(stk_val) < 6:
                    stk_val = stk_val.zfill(6)
                
                rows.append({
                    "Source File": filename,
                    "Location": location,
                    "Invoice Date": inv_date,
                    "StkNo": stk_val,
                    "Description": item.get("Description", ""),
                    "Qty": item.get("Qty", 0),
                    "NSales": item.get("NSales", 0.0),
                    "U_Retail": item.get("U_Retail", 0.0)
                })

            # 6. Calculate Totals (Manual Python Calc)
            qty_total = sum(r["Qty"] for r in rows if isinstance(r["Qty"], (int, float)))
            nsales_total = sum(r["NSales"] for r in rows if isinstance(r["NSales"], (int, float)))
            uretail_total = sum(r["U_Retail"] for r in rows if isinstance(r["U_Retail"], (int, float)))

            # Append Total Row
            rows.append({
                "Source File": filename,
                "Location": location,
                "Invoice Date": inv_date,
                "StkNo": "",
                "Description": "TOTAL",
                "Qty": qty_total,
                "NSales": nsales_total,
                "U_Retail": uretail_total
            })

    except Exception as e:
        print(f"Jaya Processing Error: {e}")
    
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        if uploaded_file_ref:
            try:
                uploaded_file_ref.delete()
            except:
                pass

    return rows
