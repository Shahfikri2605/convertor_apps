import google.generativeai as genai
import json
import tempfile
import os
import time
import pandas as pd

def upload_to_gemini(file_path, mime_type="application/pdf"):
    file = genai.upload_file(file_path, mime_type=mime_type)
    while file.state.name == "PROCESSING":
        time.sleep(1)
        file = genai.get_file(file.name)
    return file

def process_custom_invoice(pdf_bytes, filename, api_key):
    """
    Generalized extractor for JSP / Custom Service Invoices.
    Handles scanned tables with high accuracy.
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3-flash-preview") 
    
    temp_path = None
    uploaded_file_ref = None
    rows = []

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        uploaded_file_ref = upload_to_gemini(temp_path)

        # Flexible prompt to handle Custom 1-7 variations
        prompt = """
        Analyze this document and extract the main service/summary table.
        Look for columns related to dates, vehicle/lorry numbers, item descriptions, and costs.

        EXTRACT THESE FIELDS:
        1. "Date": The declaration or service date.
        2. "Reference": Lorry number or reference ID.
        3. "Description": The item or service code (e.g., 3PEX, GC-33).
        4. "Quantity": The count/qty.
        5. "Unit_Price": The rate or unit charge.
        6. "Amount": The total for that line.

        RULES:
        - Return ONLY a JSON object: {"Items": [...]}.
        - Extract ALL rows from ALL pages of the summary.
        - Convert currency strings (like '10.C' or 'RM 10') into clean numbers (10.00).
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
                "Date": item.get("Date"),
                "Lorry/Ref": item.get("Reference"),
                "Goods/Service": item.get("Description"),
                "Qty": item.get("Quantity"),
                "Unit Price": item.get("Unit_Price"),
                "Amount": item.get("Amount")
            })

    except Exception as e:
        print(f"Error processing {filename}: {e}")
    
    finally:
        if temp_path and os.path.exists(temp_path): os.unlink(temp_path)
        if uploaded_file_ref: uploaded_file_ref.delete()

    return rows
