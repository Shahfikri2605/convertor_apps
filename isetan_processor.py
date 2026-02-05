import google.generativeai as genai
import pandas as pd
import json
import tempfile
import os
import time

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

def process_isetan_pdf(pdf_bytes, filename, api_key):
    """
    Extracts iSetan Vendor/Sales History Report.
    Target Columns: No, Name, Qty, UnitPriceWithoutVAT
    """
    rows = []
    
    # Configure API
    genai.configure(api_key=api_key)
    # Using 1.5 Flash for speed/cost efficiency on tables
    model = genai.GenerativeModel("gemini-3-flash-preview") 
    
    temp_path = None
    uploaded_file_ref = None

    try:
        # 1. Save Streamlit bytes to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        # 2. Upload to Gemini
        uploaded_file_ref = upload_to_gemini(temp_path)

        # 3. Prompt (Tailored for iSetan Structure)
        prompt = """You are a Data Extraction Assistant. Extract data from this Sales/Vendor History PDF.
        
        TARGET COLUMNS TO EXTRACT:
        1. **No**: The Item Code (e.g., "ITM0714160"). Capture full alphanumeric.
        2. **Name**: The Item Description (e.g., "ZENX.ORG BITTER GOURD").
        3. **Qty**: The Quantity (e.g., 1.80).
        4. **UnitPriceWithoutVAT**: The specific column labeled "Unit Price without VAT" or the line total if singular.

        INSTRUCTIONS:
        - Extract for ALL pages.
        - Ignore "Total" rows.
        - Ensure numeric values are numbers, not strings.

        ### SCHEMA OUTPUT:
        Return strictly valid JSON.
        {
            "Items": [
                {
                    "No": "string",
                    "Name": "string",
                    "Qty": number,
                    "UnitPriceWithoutVAT": number
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

        # 5. Format Data
        items = data.get("Items", [])
        
        if items:
            for item in items:
                rows.append({
                    "Source File": filename,
                    "No": item.get("No", ""),
                    "Name": item.get("Name", ""),
                    "Qty": item.get("Qty", 0),
                    "Unit Price without VAT": item.get("UnitPriceWithoutVAT", 0.0)
                })
        else:
            # Add a placeholder row if file was empty/unreadable, so user knows it was scanned
            rows.append({
                "Source File": filename,
                "No": "NO ITEMS FOUND",
                "Name": "",
                "Qty": 0,
                "Unit Price without VAT": 0
            })

    except Exception as e:
        print(f"iSetan Processing Error: {e}")
    
    finally:
        # Cleanup local file
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        # Cleanup cloud file
        if uploaded_file_ref:
            try:
                uploaded_file_ref.delete()
            except:
                pass

    return rows
