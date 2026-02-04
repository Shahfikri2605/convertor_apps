import pdfplumber
import re
import os
import google.generativeai as genai
import json
import tempfile
import time

def extract_data_from_pdf(pdf_bytes, filename, api_key):
    """
    Extracts Maslee invoice data using Hybrid approach:
    1. pdfplumber (Fast Text)
    2. Google Gemini AI (Fallback for scans/complex layouts)
    """
    rows = []
    location_name = "Unknown"
    
    # Configure AI
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-3-flash-preview')

    try:
        # Save bytes to temp file for processing
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        with pdfplumber.open(temp_path) as pdf:
            # 1. Detect Location (Header Analysis)
            if len(pdf.pages) > 0:
                first_page_text = pdf.pages[0].extract_text()
                if first_page_text:
                    loc_match = re.search(r"(MASLEE EXPRESS|PASARAYA|E-MART|GIANT|COLD STORAGE|JAYA GROCER|BILLION|TARGET).*", first_page_text)
                    if loc_match:
                        location_name = loc_match.group(0).strip()

            # 2. Process Every Page
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text()
                
                # --- STRATEGY A: FAST TEXT EXTRACTION ---
                # If clear text exists, use your existing Regex logic (it's free & fast)
                if text and len(text) > 50:
                    lines = text.split('\n')
                    for line in lines:
                        clean_line = line.strip()
                        
                        # SKU DETECTION (9+ digits)
                        sku_match = re.search(r"(\b\d{9,}\b)", clean_line)
                        if not sku_match:
                            continue 
                        
                        sku = sku_match.group(1)
                        parts = clean_line.split()
                        if len(parts) < 5: continue
                        
                        try:
                            clean_parts = [p.replace(',', '') for p in parts]
                            all_numbers = []
                            for p in clean_parts:
                                if p.replace('.', '', 1).isdigit():
                                    all_numbers.append(float(p))
                            
                            if len(all_numbers) < 3: continue
                            
                            # Price/Cost Logic
                            last_num = all_numbers[-1]
                            cost_exc = 0.0
                            total_exc = 0.0
                            is_gp = False
                            
                            if last_num <= 100 and (last_num in [20.0, 22.0, 10.0, 0.0] or last_num.is_integer()):
                                is_gp = True
                            
                            if is_gp:
                                if len(all_numbers) < 4: continue
                                cost_exc = all_numbers[-3]
                                total_exc = all_numbers[-4]
                            else:
                                cost_exc = all_numbers[-2]
                                total_exc = all_numbers[-3]
                            
                            if cost_exc > total_exc:
                                cost_exc, total_exc = total_exc, cost_exc

                            # Description & Qty Logic
                            sku_index = -1
                            for i, p in enumerate(clean_parts):
                                if sku in p:
                                    sku_index = i
                                    break
                            
                            qty = 0
                            description_parts = []
                            found_qty = False
                            units = set(["G", "KG", "PCS", "PKT", "UNIT", "SET", "BOTTLE", "CAN", "TIN", "BOX", "CTN", "ROLL", "BDL", "PACK"])
                            
                            # Scan between SKU and End of line for Description/Qty
                            for i in range(sku_index + 1, len(clean_parts) - 3):
                                p = clean_parts[i]
                                raw_p = parts[i]
                                next_p = clean_parts[i+1] if i+1 < len(clean_parts) else ""
                                
                                if not found_qty and re.match(r"^\d+(\.\d+)?$", p):
                                    # If not a unit and next is a price -> It's Qty
                                    if next_p.upper() not in units:
                                        if i+1 < len(clean_parts) and re.match(r"^\d+(\.\d+)?$", clean_parts[i+1]):
                                            qty = float(p)
                                            found_qty = True
                                            continue
                                
                                if not found_qty:
                                    description_parts.append(raw_p)
                            
                            rows.append({
                                "Source File": filename,
                                "Location": location_name,
                                "SKU No": sku,
                                "Description": " ".join(description_parts),
                                "Qty": qty,
                                "Total Exc Tax": total_exc,
                                "Cost Exc Tax": cost_exc
                            })
                        except Exception:
                            continue

                # --- STRATEGY B: AI FALLBACK (For Scans/Messy Pages) ---
                else:
                    # If text is empty or garbage, ask Gemini to read this specific page
                    # We re-upload just this page logic or use the file
                    # To keep it simple, we skip page-by-page upload and just flag it.
                    # For a robust solution, we treat the whole file as "Scanned" if page 1 failed.
                    pass 

        # --- STRATEGY B (Full AI) ---
        # If Regex found 0 rows, it's likely a scan. Send WHOLE file to AI.
        if len(rows) == 0:
            uploaded_ref = genai.upload_file(temp_path)
            
            # Smart Prompt for Maslee Format
            prompt = """
            Extract the invoice line items from this document (Maslee/Retail format).
            Look for columns: SKU (9+ digits), Description, Qty, Total Amount, Cost/Price.
            
            Return a JSON list of objects:
            [
                {"SKU No": "...", "Description": "...", "Qty": 0.0, "Total Exc Tax": 0.0, "Cost Exc Tax": 0.0}
            ]
            If the location (e.g. MASLEE, PASARAYA) is visible, extract it too.
            """
            
            response = model.generate_content([uploaded_ref, prompt])
            
            # Clean AI Response
            clean_json = response.text.replace("```json", "").replace("```", "").strip()
            try:
                ai_data = json.loads(clean_json)
                for item in ai_data:
                    item["Source File"] = filename
                    item["Location"] = item.get("Location", location_name) # Use AI loc or regex loc
                    rows.append(item)
            except:
                pass # AI failed to give valid JSON

            # Cleanup AI file
            uploaded_ref.delete()

    except Exception as e:
        print(f"Error processing {filename}: {e}")
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    return rows
