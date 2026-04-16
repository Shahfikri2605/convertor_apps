import google.generativeai as genai
import json
import tempfile
import os
import time

def upload_to_gemini(file_path, mime_type="application/pdf"):
    file = genai.upload_file(file_path, mime_type=mime_type)
    while file.state.name == "PROCESSING":
        time.sleep(1)
        file = genai.get_file(file.name)
    if file.state.name != "ACTIVE":
        raise Exception(f"Gemini File Error: {file.state.name}")
    return file

def process_jsp_invoice(pdf_bytes, filename, api_key):
    """
    Extracts JSP Corporate Export Service Summary.
    Target Columns: Decl. Date, Lorry No, Goods, Qty, Unit Chrg, Amount
    """
    rows = []
    genai.configure(api_key=api_key)
    # Gemini 1.5 Flash is excellent for tabular extraction from images/PDFs
    model = genai.GenerativeModel("gemini-3-flash-preview") 
    
    temp_path = None
    uploaded_file_ref = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        uploaded_file_ref = upload_to_gemini(temp_path)

        # Prompt specifically designed for the JSP Summary table structure [cite: 97, 108, 118]
        prompt = """
        Extract the 'Export Service Summary' table from this document. 
        Focus on the data between Page 2 and Page 7.

        COLUMNS TO EXTRACT:
        1. "Decl_Date": The date in DD/MM/YYYY format.
        2. "Lorry_No": The vehicle number (e.g., JPH9329 or JRF9586). If empty, leave as null.
        3. "Goods": The item code (e.g., 3PEX-E, GC-33, GC-CHK63).
        4. "Qty": The quantity as a number.
        5. "Unit_Chrg": The unit price/charge.
        6. "Amount": The total for that row.

        REQUIREMENTS:
        - Return ONLY a JSON object with a key "Items" containing a list of these objects.
        - Process EVERY page that contains table rows.
        - Ignore headers and the final "TOTAL" summary row.
        - Fix common OCR errors: if a number looks like '10.C', convert it to 10.00.
        """

        response = model.generate_content(
            [uploaded_file_ref, prompt],
            generation_config={"response_mime_type": "application/json"}
        )

        data = json.loads(response.text)
        items = data.get("Items", [])
        
        for item in items:
            rows.append({
                "Source File": filename,
                "Decl. Date": item.get("Decl_Date"),
                "Lorry No": item.get("Lorry_No"),
                "Goods": item.get("Goods"),
                "Qty": item.get("Qty"),
                "Unit Chrg": item.get("Unit_Chrg"),
                "Amount": item.get("Amount")
            })

    except Exception as e:
        print(f"JSP Processing Error: {e}")
    
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        if uploaded_file_ref:
            uploaded_file_ref.delete()

    return rows
