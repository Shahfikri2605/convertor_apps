
import re
import os
import fitz  
import cv2
import numpy as np
import pandas as pd
import json
import time
from pyzbar.pyzbar import decode
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import tempfile

def extract_qr_from_pdf(pdf_path):
    """
    Opens a PDF, converts the first page to an image, and detects QR codes.
    """
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=300)
        
        img_data = np.frombuffer(pix.samples, dtype=np.uint8)
        img = img_data.reshape(pix.h, pix.w, pix.n)

        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        
        decoded_objects = decode(img)

        for obj in decoded_objects:
            url = obj.data.decode("utf-8")
            if "http" in url:
                return url
        
        return None
    except Exception as e:
        print(f" [Error processing QR]: {e}")
        return None

def get_uuid_from_url(url):
    """
    Visits the URL using Selenium to bypass blocks and reads the UUID.
    """
    if not url: return None
    
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    # Helper to prevent detection
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get(url)
        time.sleep(5) # Wait for LHDN to load
        
        page_text = driver.find_element("tag name", "body").text
        
        # Search for UUID patterns
        match = re.search(r'([A-Z0-9]{8,}-[A-Z0-9]{8,})', page_text, re.IGNORECASE)
        if not match:
             match = re.search(r'UUID[:\s]*([a-zA-Z0-9-]+)', page_text, re.IGNORECASE)

        if match:
            return match.group(1)
        else:
            return "Not Found"
    except Exception as e:
        print(f" [Browser Error]: {e}")
        return "Error"
    finally:
        if driver: driver.quit()

def process_single_invoice(pdf_bytes, filename, api_key):
    """
    Main logic to process a single PDF file (bytes) from Streamlit.
    """
    genai.configure(api_key=api_key)
    
    # Save bytes to a temporary file for processing
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        temp_path = tmp.name

    try:
        # 1. Try QR Code First
        qr_link = extract_qr_from_pdf(temp_path)
        uuid = get_uuid_from_url(qr_link)
        
        # 2. Extract Data via AI
        ai_data = extract_with_ai(temp_path, found_uuid=uuid, api_key=api_key)
        
        # 3. Clean up data rows
        rows = []
        items = ai_data.get("Items", [])
        if not items:
            items = [{"No": "", "Description": "", "Discount Amount": "", "Amount": ""}]

        for item in items:
            row = {
                "FileName": filename,
                "Bill To": ai_data.get("Bill To", ""),
                "Invoice No.": ai_data.get("Invoice No", ""),
                "Invoice Date": ai_data.get("Invoice Date", ""),
                "UUID": ai_data.get("UUID", uuid if uuid else ""), # Use scanned UUID if AI misses it
                "No": item.get("No", ""),
                "Item/ Cross Ref No": item.get("Item/ Cross Ref No", ""),
                "Description": item.get("Description", ""),
                "Discount Amount": item.get("Discount Amount", ""),
                "Amount": item.get("Amount", ""),
                "Total Amount": ai_data.get("Total Amount", ""),
                "Total Discount": ai_data.get("Total Discount", ""),
                "Total MYR": ai_data.get("Total MYR", "")
            }
            rows.append(row)
            
        return rows

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def extract_with_ai(pdf_path, found_uuid=None, api_key=""):
    """
    Uploads to Gemini.
    """
    try:
        sample_file = genai.upload_file(path=pdf_path, display_name="Invoice")
        
        # Wait for processing
        while sample_file.state.name == "PROCESSING":
            time.sleep(1)
            sample_file = genai.get_file(sample_file.name)

        model = genai.GenerativeModel("gemini-3-flash-preview") # 1.5-flash is faster/cheaper

        uuid_instruction = ""
        if not found_uuid or found_uuid in ["Not Found", "Error"]:
            uuid_instruction = '"UUID": "Extract the UUID visible on the document (usually 32 chars long)",'
        
        prompt = f"""
        Extract the invoice data into strict JSON.
        
        JSON Structure:
        {{
            "Bill To": "",
            "Invoice No": "",
            "Invoice Date": "",
            {uuid_instruction}
            "Total MYR": "Grand Total",
        }}
        """

        response = model.generate_content([sample_file, prompt])
        raw_text = response.text.replace("```json", "").replace("```", "").strip()
        
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
             # Basic fallback cleanup
            start = raw_text.find('{')
            end = raw_text.rfind('}') + 1
            data = json.loads(raw_text[start:end])

        return data

    except Exception as e:
        print(f" [AI Error]: {e}")

        return {}
