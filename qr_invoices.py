import json
import os
import re
import tempfile
import time
import cv2
import fitz  # PyMuPDF
import google.generativeai as genai
import numpy as np
import pandas as pd
from pyzbar.pyzbar import decode
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def get_driver():
    """Initializes Selenium Chrome driver compatible with both Local and Streamlit Cloud."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Streamlit Community Cloud (Debian Linux path)
    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
        return webdriver.Chrome(service=service, options=chrome_options)

    # Local development fallback (Windows/macOS)
    from webdriver_manager.chrome import ChromeDriverManager

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


def extract_qr_from_pdf(pdf_path):
    """Iterates through all pages of a PDF, converts to images, and detects QR code URLs."""
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
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
    """Extracts UUID from the URL directly or loads the page via Selenium as a fallback."""
    if not url:
        return None

    # Fast Path: Check if standard UUID format exists directly in the URL query/path
    url_uuid_match = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        url,
    )
    if url_uuid_match:
        return url_uuid_match.group(0)

    # Fallback to headless browser rendering
    driver = None
    try:
        driver = get_driver()
        driver.get(url)
        time.sleep(5)  # Allow JS/LHDN portal to populate data

        page_text = driver.find_element("tag name", "body").text

        match = re.search(
            r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
            page_text,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"UUID[:\s]*([a-zA-Z0-9-]+)", page_text, re.IGNORECASE
            )

        return match.group(1) if match else "Not Found"
    except Exception as e:
        print(f" [Browser Error]: {e}")
        return "Error"
    finally:
        if driver:
            driver.quit()


def extract_with_ai(pdf_path, found_uuid=None, api_key=""):
    """Extracts metadata via Gemini API if missing from QR scanning."""
    try:
        sample_file = genai.upload_file(path=pdf_path, display_name="Invoice")

        while sample_file.state.name == "PROCESSING":
            time.sleep(1)
            sample_file = genai.get_file(sample_file.name)

        model = genai.GenerativeModel("gemini-1.5-flash")

        uuid_instruction = ""
        if not found_uuid or found_uuid in ["Not Found", "Error"]:
            uuid_instruction = '"UUID": "Extract the UUID visible on the document (usually 32-36 characters long)",'

        prompt = f"""
        Extract the invoice data into strict JSON matching this structure:
        {{
            "Bill To": "",
            "Supplier Name": "",
            "PO No": "",
            "Date": "",
            "Invoice No": "",
            "Invoice Date": "",
            {uuid_instruction}
            "Total MYR": "Grand Total"
        }}
        """

        response = model.generate_content([sample_file, prompt])
        raw_text = (
            response.text.replace("```json", "").replace("```", "").strip()
        )

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            start = raw_text.find("{")
            end = raw_text.rfind("}") + 1
            data = json.loads(raw_text[start:end])

        return data
    except Exception as e:
        print(f" [AI Error]: {e}")
        return {}


def process_single_invoice(pdf_bytes, filename, api_key):
    """Processes uploaded invoice bytes, orchestrating QR scanning, headless scraping, and Gemini extraction."""
    genai.configure(api_key=api_key)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        temp_path = tmp.name

    try:
        # 1. Scan all pages for QR code
        qr_link = extract_qr_from_pdf(temp_path)

        # 2. Extract UUID from link (or through browser)
        uuid = get_uuid_from_url(qr_link)

        # 3. Extract Invoice Header Data with Gemini
        ai_data = extract_with_ai(temp_path, found_uuid=uuid, api_key=api_key)

        resolved_uuid = (
            uuid
            if (uuid and uuid not in ["Not Found", "Error"])
            else ai_data.get("UUID", "")
        )

        rows = [
            {
                "FileName": filename,
                "Supplier Name": ai_data.get("Supplier Name", ""),
                "Bill To": ai_data.get("Bill To", ""),
                "PO No": ai_data.get("PO No", ""),
                "Date": ai_data.get("Date", ""),
                "Invoice No.": ai_data.get("Invoice No", ""),
                "Invoice Date": ai_data.get("Invoice Date", ""),
                "UUID": resolved_uuid,
                "Total MYR": ai_data.get("Total MYR", ""),
            }
        ]

        return rows
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
