import google.generativeai as genai
import json
import tempfile
import os
import time

def process_kastam_pdf(pdf_bytes, filename, api_key):
    """
    Extracts Kastam/Customs Permit data (FAST MODE).
    Sends the WHOLE file in 1 Request.
    """
    rows = []
    
    # Configure API
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-3-flash-preview')
    
    temp_path = None
    uploaded_file = None

    try:
        # 1. Save temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        # 2. Upload the WHOLE file (1 Request)
        uploaded_file = genai.upload_file(temp_path, mime_type="application/pdf")
        
        # Wait for processing
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = genai.get_file(uploaded_file.name)

        # 3. Prompt
        prompt = """
        Extract the table rows from ALL pages of this Kastam Customs Permit.
        Return ONLY valid JSON.
        
        Target Columns:
        - Decl_Date (Declaration Date)
        - Lorry_No (Vehicle Number)
        - Goods (Description of Goods)
        - Exp_Date (Export/Import Date)
        - Qty (Quantity)
        - Unit_Chrg (Unit Charge/Price)

        JSON Schema:
        {
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

        # 4. Generate Content (One Big Request)
        response = model.generate_content(
            [uploaded_file, prompt],
            generation_config={'response_mime_type': 'application/json'}
        )

        # 5. Parse Data
        try:
            data = json.loads(response.text)
            items = data.get("Line_Items", [])
            
            if items:
                for item in items:
                    item['Source File'] = filename
                    # Note: In fast mode, we might lose accurate "Page No" tracking
                    # unless we ask the AI to include it in the JSON schema.
                    rows.append(item)
        except Exception as e:
            print(f"JSON Error: {e}")

    except Exception as e:
        print(f"Kastam Error: {e}")

    finally:
        # Cleanup
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        if uploaded_file:
            try:
                genai.delete_file(uploaded_file.name)
            except:
                pass

    return rows
