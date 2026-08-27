import io
import re
import pdfplumber
import pandas as pd

# Header metadata extraction patterns
HEADER_PATTERNS = {
    "Invoice No": re.compile(r"INVOICE\s*NO\s*:\s*([A-Za-z0-9\-]+)", re.IGNORECASE),
    "Invoice Date": re.compile(r"INVOICE\s*DATE\s*:\s*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", re.IGNORECASE),
    "DO No": re.compile(r"DO\s*NO\s*:\s*([A-Za-z0-9\-]+)", re.IGNORECASE),
    "Delivery Date": re.compile(r"DELIVERY\s*DATE\s*:\s*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", re.IGNORECASE),
    "Order No": re.compile(r"ORDER\s*NO\s*:\s*([A-Za-z0-9\-]+)", re.IGNORECASE),
    "Customer No": re.compile(r"CUSTOMER\s*NO\s*:\s*([A-Za-z0-9\-]+)", re.IGNORECASE),
    "Currency": re.compile(r"CURRENCY\s*:\s*([A-Za-z]+)", re.IGNORECASE),
}

# Matches the trailing numeric block: [Size / Unit] [Order Pack] [Qty] [Qty Price] [Amount] [BCRS]
# Supports Size as digits (00000) or text (PK, BO, EA, KGM, etc.)
TRAILING_NUMERIC_PATTERN = re.compile(
    r"\s+([A-Za-z0-9]{2,6})\s+(\d+)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)$"
)

# Matches leading [NO] [Optional Item Code] [Cust Item Code]
LEADING_PATTERN = re.compile(
    r"^(?:(\d+)\s+)?(?:(\d{8})\s+)?(\d{7})\s+(.*)$"
)


def clean_numeric(val_str):
    """Clean string numbers into standard float values."""
    if not val_str:
        return 0.0
    val_clean = str(val_str).replace(",", "").strip()
    try:
        return float(val_clean)
    except ValueError:
        return 0.0


def extract_headers_from_text(text):
    """Extract invoice-level metadata from the page header."""
    headers = {
        "Sold To": "COLD STORAGE SINGAPORE (1983) PTE LTD",
        "Delivered To": "Cold Storage Singapore (1983) Pte Ltd",
        "Invoice No": "",
        "Invoice Date": "",
        "DO No": "",
        "Delivery Date": "",
        "Order No": "",
        "Customer No": "",
        "Currency": "SGD"
    }

    sold_to_match = re.search(r"SOLD\s*TO\s*:\s*(.*?)(?=DELIVERED\s*TO\s*:|INVOICE\s*NO|DO\s*NO|$)", text, re.DOTALL | re.IGNORECASE)
    if sold_to_match:
        sold_text = " ".join([l.strip() for l in sold_to_match.group(1).strip().splitlines() if l.strip()])
        if sold_text:
            headers["Sold To"] = sold_text

    deliv_to_match = re.search(r"DELIVERED\s*TO\s*:\s*(.*?)(?=INVOICE\s*NO|DO\s*NO|TAX\s*INVOICE|$)", text, re.DOTALL | re.IGNORECASE)
    if deliv_to_match:
        deliv_text = " ".join([l.strip() for l in deliv_to_match.group(1).strip().splitlines() if l.strip()])
        if deliv_text:
            headers["Delivered To"] = deliv_text

    for key, pattern in HEADER_PATTERNS.items():
        m = pattern.search(text)
        if m:
            headers[key] = m.group(1).strip()

    return headers


def process_cs_giant_pdf(pdf_bytes, file_name=""):
    """
    Extracts all line items across all pages of a Cold Storage / Giant Consignment invoice PDF.
    Handles invoices with/without Item Code and with varying Size units.
    """
    all_extracted_rows = []
    
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        global_headers = {}

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            page_headers = extract_headers_from_text(text)
            if not global_headers.get("Invoice No"):
                global_headers = page_headers

            lines = text.split("\n")

            for raw_line in lines:
                line = raw_line.strip()

                # Skip header/summary noise lines
                if not line or any(k in line.upper() for k in [
                    "TAX INVOICE", "CUST ITEM", "QTY PRICE", "BCRS DEPOSIT",
                    "PAGE ", "REMARKS :", "GROSS TOTAL", "AMOUNT DUE", "ADD GST @"
                ]):
                    continue

                # Remove layout artifact pipes and collapse whitespace
                line_normalized = re.sub(r"\|", " ", line)
                line_normalized = re.sub(r"\s+", " ", line_normalized).strip()

                # Step 1: Check if the end of line matches the 6 trailing numeric columns
                trailing_match = TRAILING_NUMERIC_PATTERN.search(line_normalized)

                if trailing_match:
                    size, pack, qty, price, amount, bcrs = trailing_match.groups()
                    left_part = line_normalized[:trailing_match.start()].strip()

                    # Step 2: Parse the leading identifiers (NO, Item Code, Cust Item Code, Description)
                    lead_match = LEADING_PATTERN.match(left_part)

                    if lead_match:
                        row_no, item_code, cust_code, desc = lead_match.groups()

                        clean_desc = desc.lstrip("*").strip()

                        row_data = {
                            "Sold To": global_headers.get("Sold To", page_headers.get("Sold To", "")),
                            "Delivered To": global_headers.get("Delivered To", page_headers.get("Delivered To", "")),
                            "Invoice No": global_headers.get("Invoice No", page_headers.get("Invoice No", "")),
                            "Invoice Date": global_headers.get("Invoice Date", page_headers.get("Invoice Date", "")),
                            "DO No": global_headers.get("DO No", page_headers.get("DO No", "")),
                            "Delivery Date": global_headers.get("Delivery Date", page_headers.get("Delivery Date", "")),
                            "Order No": global_headers.get("Order No", page_headers.get("Order No", "")),
                            "Customer No": global_headers.get("Customer No", page_headers.get("Customer No", "")),
                            "Item Code": item_code if item_code else "",
                            "Cust Item Code": cust_code,
                            "Description": clean_desc,
                            "Size": size,
                            "Order Pack": pack,
                            "Qty": clean_numeric(qty),
                            "Qty Price": clean_numeric(price),
                            "Amount": clean_numeric(amount),
                            "BCRS Deposit": clean_numeric(bcrs),
                            "Source File": file_name
                        }
                        all_extracted_rows.append(row_data)

                else:
                    # Handle multi-line description wrap
                    if not re.search(r"^\d{7}", line_normalized) and not any(k in line_normalized for k in ["SOLD TO", "DELIVERED TO", "INVOICE"]):
                        if all_extracted_rows:
                            all_extracted_rows[-1]["Description"] = (
                                all_extracted_rows[-1]["Description"] + " " + line_normalized.lstrip("*").strip()
                            ).strip()

    return all_extracted_rows
