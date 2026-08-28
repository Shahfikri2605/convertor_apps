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
    """Initializes Selenium Chrome driver compatible with Local and Streamlit Cloud."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Streamlit Cloud Debian Path
    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
        return webdriver.Chrome(service=service, options=chrome_options)

    # Local Fallback (Windows / Mac)
    from webdriver_manager.chrome import ChromeDriverManager

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


def extract_qr_and_links_per_page(pdf_path):
    """
    Extracts both visual QR code URLs and embedded text hyperlinks
    (e.g., 'LHDN Validated Link') for each page.
    Returns: { page_number (1-indexed): url }
    """
    page_urls = {}
    try:
        doc = fitz.open(pdf_path)
        for page_idx in range(len(doc)):
            page_num = page_idx + 1
            page = doc.load_page(page_idx)

            # 1. Check embedded clickable PDF links (e.g. LHDN Validated Link)
            for link in page.get_links():
                uri = link.get("uri", "")
                if uri and "http" in uri:
                    page_urls[page_num] = uri
                    break

            if page_num in page_urls:
                continue

            # 2. Check visual QR code image
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
                    page_urls[page_num] = url
                    break
    except Exception as e:
        print(f" [Link/QR Extraction Error]: {e}")
    return page_urls


def get_uuid_from_url(url, driver=None):
    """
    Extracts LHDN UUID from URL regex directly or renders page via Selenium fallback.
    Handles standard GUIDs and 26-30 char alphanumeric e-Invoice identifiers.
    """
    if not url:
        return ""

    # 1. Direct Regex check from the URL query/path (avoids browser if present)
    # Check standard UUID or long alphanumeric ID in the URL endpoint
    url_segment = url.split("?")[0].split("/")[-1]
    match = re.search(r"([A-Z0-9]{20,36})", url_segment, re.IGNORECASE)
    if match:
        return match.group(1)

    # 2. Browser Fallback
    local_driver = False
    if driver is None:
        try:
            driver = get_driver()
            local_driver = True
        except Exception as e:
            print(f" [Driver Init Error]: {e}")
            return ""

    try:
        driver.get(url)
        time.sleep(4)  # Wait for LHDN dynamic validation page to populate
        page_text = driver.find_element("tag name", "body").text

        # Search for standard hyphenated UUID or raw alphanumeric invoice ID
        match = re.search(
            r"([0-9a-zA-Z]{8}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{12})",
            page_text,
        )
        if not match:
            match = re.search(
                r"([A-Z0-9]{24,36})", page_text
            )  # LHDN base32 style
        if not match:
            match = re.search(
                r"UUID[:\s]*([a-zA-Z0-9-]+)", page_text, re.IGNORECASE
            )

        return match.group(1) if match else "Not Found"
    except Exception as e:
        print(f" [Browser Scraping Error]: {e}")
        return "Error"
    finally:
        if local_driver and driver:
            driver.quit()


def extract_with_ai(pdf_path, api_key=""):
    """
    Sends the multi-page PDF to Gemini to extract all invoices as an array of objects.
    """
    try:
        sample_file = genai.upload_file(
            path=pdf_path, display_name="Invoices PDF"
        )

        while sample_file.state.name == "PROCESSING":
            time.sleep(1)
            sample_file = genai.get_file(sample_file.name)

        model = genai.GenerativeModel("gemini-3-flash-preview")

        prompt = """
        This PDF document may contain ONE or MULTIPLE separate invoices.
        Extract every invoice found in the document into a JSON array of objects.

        Return strictly a JSON array matching this format:
        [
            {
                "Page Number": 1,
                "Supplier Name": "",
                "Bill To": "",
                "PO No": "",
                "Date": "",
                "Invoice No": "",
                "Invoice Date": "",
                "UUID": "Extract any 26-36 char UUID/Validation ID if printed on page, else empty",
                "Total MYR": "Grand Total amount as number or formatted string"
            }
        ]

        Rules:
        - "Page Number": The physical PDF page number (1-indexed) where the total or validation stamp of this invoice appears.
        - Ensure every distinct invoice has its own entry.
        """

        response = model.generate_content([sample_file, prompt])
        raw_text = (
            response.text.replace("```json", "").replace("```", "").strip()
        )

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            start = raw_text.find("[")
            end = raw_text.rfind("]") + 1
            data = json.loads(raw_text[start:end])

        return data if isinstance(data, list) else [data]

    except Exception as e:
        print(f" [AI Error]: {e}")
        return []


def process_single_invoice(pdf_bytes, filename, api_key):
    """
    Main pipeline to process an uploaded multi-invoice PDF.
    """
    genai.configure(api_key=api_key)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        temp_path = tmp.name

    driver = None
    try:
        # 1. Scan every page for visual QR codes and clickable embedded links
        page_urls = extract_qr_and_links_per_page(temp_path)

        # 2. Extract UUID for every detected link
        page_uuids = {}
        if page_urls:
            try:
                driver = get_driver()
            except Exception:
                driver = None

            for page_no, url in page_urls.items():
                page_uuids[page_no] = get_uuid_from_url(url, driver=driver)

        # 3. Extract invoice header data via Gemini
        ai_invoices = extract_with_ai(temp_path, api_key=api_key)

        # 4. Map extracted data rows
        rows = []
        for inv in ai_invoices:
            page_no = inv.get("Page Number", 1)

            # Look up scanned UUID on this page; fallback to AI-detected UUID
            scanned_uuid = page_uuids.get(page_no, "")
            resolved_uuid = (
                scanned_uuid
                if (scanned_uuid and scanned_uuid not in ["Not Found", "Error"])
                else inv.get("UUID", "")
            )

            row = {
                "FileName": filename,
                "PO No": inv.get("PO No", ""),
                "Date": inv.get("Date", ""),
                "Invoice No.": inv.get("Invoice No", ""),
                "Invoice Date": inv.get("Invoice Date", ""),
                "UUID": resolved_uuid,
                "Total MYR": inv.get("Total MYR", ""),
                "Supplier Name": inv.get("Supplier Name", ""),
                "Bill To": inv.get("Bill To", ""),
            }
            rows.append(row)

        return rows

    finally:
        if driver:
            driver.quit()
        if os.path.exists(temp_path):
            os.unlink(temp_path)
