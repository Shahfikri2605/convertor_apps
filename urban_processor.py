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

def process_urban_pdf(pdf_bytes, filename, api_key):
    """
    Orchestrates the Urban Report extraction:
    1. Temp File Save
    2. Upload to Gemini
    3. Extract JSON
    4. Clean Data (Remove 'A', Fix Qty)
    """
    rows = []
    
    
    genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel("gemini-3-flash-preview") 
    
    temp_path = None
    uploaded_file_ref = None

    try:
        # 1. Save Streamlit bytes to a real file (Gemini needs a path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        # 2. Upload to Gemini
        uploaded_file_ref = upload_to_gemini(temp_path)

        # 3. Prompt for Extraction
        prompt = """
        Analyze this Sales Report PDF. Extract the following columns for every item row found in the table.
        Return the data as a pure JSON list of objects.
        
        Columns to extract:
        1. Product No (Extract as is, e.g., A 40-96-00274-0)
        2. Description (The main product name)
        3. Pack/Size (The size unit, e.g., 1x500GM)
        4. Qty (The quantity number)
        5. Net Sales Incl GST (The final amount column)

        JSON Schema:
        [
            {
                "Product No": "string",
                "Description": "string",
                "Pack/Size": "string",
                "Qty": "number",
                "Net Sales Incl GST": "number"
            }
        ]
        """

        response = model.generate_content(
            [uploaded_file_ref, prompt],
            generation_config={"response_mime_type": "application/json"}
        )

        # 4. Parse & Clean Data
        raw_json = response.text
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            # Fallback cleanup
            clean_json = raw_json.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)

        if data:
            # Convert to DataFrame for easier cleaning
            df = pd.DataFrame(data)

            # CLEAN: Remove 'A' from Product No
            if "Product No" in df.columns:
                df["Product No"] = df["Product No"].astype(str).str.replace("A", "", regex=False).str.strip()
                df["Product No"] = df["Product No"].astype(str).str.replace("P", "", regex=False).str.strip()

            # CLEAN: Format Qty to Number
            if "Qty" in df.columns:
                df["Qty"] = pd.to_numeric(df["Qty"], errors='coerce').fillna(0)
            
            # CLEAN: Format Sales to Number
            if "Net Sales Incl GST" in df.columns:
                 df["Net Sales Incl GST"] = pd.to_numeric(df["Net Sales Incl GST"], errors='coerce').fillna(0)

            # Add Source File
            df["Source File"] = filename

            # Convert back to list of dicts for the App
            rows = df.to_dict('records')

    except Exception as e:
        print(f"Urban Processing Error: {e}")
    
    finally:
        # Cleanup: Delete local temp file
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
      
        if uploaded_file_ref:
            try:
                uploaded_file_ref.delete()
            except:
                pass

    return rows
