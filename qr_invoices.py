import json
import os
import re
import tempfile
import time
import cv2
from google import genai
from google.genai import types
import numpy as np
import pandas as pd
import pymupdf
from pydantic import BaseModel, Field
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


# --- Schema Definition for Gemini Structured Output ---
class InvoiceItem(BaseModel):
    page_number: int = Field(
        ...,
        description="Physical 1-indexed PDF page number where this invoice or total appears",
    )
    supplier_name: str = Field(default="", description="Supplier or vendor name")
    bill_to: str = Field(default="", description="Customer or Bill To entity")
    po_no: str = Field(default="", description="Purchase Order Number")
    date: str = Field(default="", description="General document date")
    invoice_no: str = Field(default="", description="Invoice Number")
    invoice_date: str = Field(default="", description="Date of the invoice")
    uuid: str = Field(
        default="",
        description="Extract 26-36 char validation UUID or alphanumeric ID printed anywhere near footers/stamps",
    )
    validation_link: str = Field(
        default="",
        description="Extract raw validation URL if printed as text",
    )
    total_myr: str = Field(default="", description="Grand Total amount")


def get_driver():
    """Initializes headless Selenium Chrome driver compatible with Local and Streamlit Cloud."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions")
    # DO NOT use --single-process; it causes Chromium container crashes
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Streamlit Cloud Debian Chromium Path
    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
        return webdriver.Chrome(service=service, options=chrome_options)
    elif os.path.exists("/usr/bin/chromium-browser"):
        chrome_options.binary_location = "/usr/bin/chromium-browser"
        service = Service("/usr/bin/chromedriver")
        return webdriver.Chrome(service=service, options=chrome_options)

    # Local Fallback (Windows / macOS)
    from webdriver_manager.chrome import ChromeDriverManager

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


def _decode_with_cv2(image):
    """Detects and decodes QR codes using OpenCV's built-in detector."""
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(image)
    return data.strip() if data else None


def extract_qr_from_scan(image_bgr):
    """Tries multiple image-processing techniques using OpenCV to detect faint/scanned QR codes."""
    # 1. Direct pass
    val = _decode_with_cv2(image_bgr)
    if val:
        return val

    # 2. Grayscale + CLAHE Contrast Boost
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    val = _decode_with_cv2(enhanced)
    if val:
        return val

    # 3. Adaptive Thresholding
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 10
    )
    val = _decode_with_cv2(thresh)
    if val:
        return val

    # 4. Otsu Binarization
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    val = _decode_with_cv2(otsu)
    if val:
        return val

    return None


def extract_qr_and_links_per_page(pdf_path):
    """
    Extracts visual QR code URLs and embedded hyperlinks per page.
    Returns: { page_number (1-indexed): url }
    """
    page_urls = {}
    try:
        doc = pymupdf.open(pdf_path)
        for page_idx in range(len(doc)):
            page_num = page_idx + 1
            page = doc.load_page(page_idx)

            # 1. Check embedded clickable PDF links
            for link in page.get_links():
                uri = link.get("uri", "")
                if uri and "http" in uri:
                    page_urls[page_num] = uri
                    break

            if page_num in page_urls:
                continue

            # 2. Render page at 300 DPI for high-resolution scan analysis
            pix = page.get_pixmap(dpi=300)
            img_data = np.frombuffer(pix.samples, dtype=np.uint8)
            img = img_data.reshape(pix.h, pix.w, pix.n)

            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            url = extract_qr_from_scan(img)
            if url and "http" in url:
                page_urls[page_num] = url
        doc.close()
    except Exception as e:
        print(f" [Link/QR Extraction Error]: {e}")
    return page_urls


def get_uuid_from_url(url, driver=None):
    """
    Extracts LHDN UUID from URL string directly or loads via Selenium fallback.
    Handles standard GUIDs and 26-36 char alphanumeric e-Invoice identifiers.
    """
    if not url:
        return ""

    # 1. Fast regex extraction from URL query or path
    url_segment = url.split("?")[0].split("/")[-1]
    match = re.search(r"([A-Z0-9]{20,36})", url_segment, re.IGNORECASE)
    if match:
        return match.group(1)

    # 2. Headless Browser fallback
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
        time.sleep(3)
        page_text = driver.find_element("tag name", "body").text

        match = re.search(
            r"([0-9a-zA-Z]{8}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{12})",
            page_text,
        )
        if not match:
            match = re.search(r"([A-Z0-9]{24,36})", page_text)
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
    Uploads the multi-page PDF using the google-genai SDK to extract
    all invoice records as a strictly validated list of objects.
    """
    try:
        client = genai.Client(api_key=api_key)

        uploaded_file = client.files.upload(
            file=pdf_path,
            config=types.UploadFileConfig(mime_type="application/pdf"),
        )

        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = client.files.get(name=uploaded_file.name)

        prompt = (
            "This PDF document contains ONE or MULTIPLE separate invoices. "
            "Extract every distinct invoice found in the document according to the schema. "
            "Make sure 'page_number' corresponds to the physical 1-indexed page where the invoice total or signature appears."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[InvoiceItem],
                temperature=0.1,
            ),
        )

        # Delete the uploaded file from Google storage after inference
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass

        raw_json = json.loads(response.text)
        return raw_json if isinstance(raw_json, list) else [raw_json]

    except Exception as e:
        print(f" [AI Error]: {e}")
        return []


def process_single_invoice(pdf_bytes, filename, api_key):
    """Main processing pipeline for multi-invoice PDF files."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        temp_path = tmp.name

    driver = None
    try:
        # 1. Scan physical/visual QR codes and embedded links per page
        page_urls = extract_qr_and_links_per_page(temp_path)

        # 2. Resolve UUIDs from URLs
        page_uuids = {}
        if page_urls:
            try:
                driver = get_driver()
            except Exception as e:
                print(f" [Selenium Driver Launch Error]: {e}")
                driver = None

            for page_no, url in page_urls.items():
                page_uuids[page_no] = get_uuid_from_url(url, driver=driver)

        # 3. Extract invoice header data via Gemini
        ai_invoices = extract_with_ai(temp_path, api_key=api_key)

        # 4. Consolidate results
        rows = []
        for inv in ai_invoices:
            page_no = inv.get("page_number", 1)

            # Match scanned QR/link UUID first
            scanned_uuid = page_uuids.get(page_no, "")

            # Fallback to AI-extracted link or printed UUID
            if not scanned_uuid:
                ai_link = inv.get("validation_link", "")
                if ai_link:
                    scanned_uuid = get_uuid_from_url(ai_link, driver=driver)

            resolved_uuid = (
                scanned_uuid
                if (scanned_uuid and scanned_uuid not in ["Not Found", "Error"])
                else inv.get("uuid", "")
            )

            row = {
                "FileName": filename,
                "PO No": inv.get("po_no", ""),
                "Date": inv.get("date", ""),
                "Invoice No.": inv.get("invoice_no", ""),
                "Invoice Date": inv.get("invoice_date", ""),
                "UUID": resolved_uuid,
                "Total MYR": inv.get("total_myr", ""),
                "Supplier Name": inv.get("supplier_name", ""),
                "Bill To": inv.get("bill_to", ""),
            }
            rows.append(row)

        return rows

    finally:
        if driver:
            driver.quit()
        if os.path.exists(temp_path):
            os.unlink(temp_path)
