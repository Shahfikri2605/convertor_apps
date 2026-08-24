import io
import re
import pdfplumber
import pandas as pd

def extract_text_in_box(words, x0, y0, x1, y1):
    """Filters words inside a coordinate bounding box and joins them in reading order."""
    matched = [
        w for w in words
        if w['x0'] >= x0 and w['x1'] <= x1 and w['top'] >= y0 and w['bottom'] <= y1
    ]
    matched.sort(key=lambda w: (round(w['top'] / 3) * 3, w['x0']))
    return " ".join(w['text'] for w in matched).strip()

def process_cs_giant_pdf(file_bytes, filename=""):
    all_rows = []

    seller_name = "Zenxin Agri-Organic Food Pte Ltd"
    seller_address = "Blk14 Wholesale Centre #01-25, SINGAPORE, 110014"
    biz_reg_no = "200616582M"
    gst_reg_no = "200616582M"

    sold_to = ""
    delivered_to = ""
    invoice_no = ""
    invoice_date = ""
    do_no = ""
    delivery_date = ""
    order_no = ""
    order_date = ""
    payment_due = ""
    customer_no = ""
    currency = "SGD"

    # Line Item Regex
    row_pattern = re.compile(
        r"^\s*(\d+)\s+"                     # Line No
        r"(\d+)\s+"                         # Item Code
        r"(\d+)\s+"                         # Cust Item Code
        r"(.+?)\s+"                         # Description
        r"([0-9a-zA-Z]{4,5})\s+"            # Size
        r"(\d+)\s+"                         # Order Pack
        r"([\d,]+\.?\d*)\s+"                # Qty
        r"([\d,]+\.?\d*)\s+"                # Qty Price
        r"([\d,]+\.?\d*)\s+"                # Amount
        r"([\d,]+\.?\d*)\s*$",              # BCRS Deposit
        re.MULTILINE
    )

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        first_page = pdf.pages[0]
        w, h = float(first_page.width), float(first_page.height)
        words = first_page.extract_words()
        full_p1_text = first_page.extract_text() or ""

        # --- 1. Coordinate-based Header Extraction ---
        # Sold To (Left Column, Upper Box)
        raw_sold = extract_text_in_box(words, 0, h * 0.05, w * 0.58, h * 0.20)
        raw_sold = re.sub(r"^.*?SOLD\s*TO\s*:\s*", "", raw_sold, flags=re.I).strip()
        sold_to = raw_sold if raw_sold else "COLD STORAGE SINGAPORE (1983) PTE LTD"

        # Delivered To (Left Column, Lower Box)
        raw_deliv = extract_text_in_box(words, 0, h * 0.20, w * 0.58, h * 0.32)
        raw_deliv = re.sub(r"^.*?DELIVERED\s*TO\s*:\s*", "", raw_deliv, flags=re.I).strip()
        delivered_to = raw_deliv if raw_deliv else "Cold Storage Singapore (1983) Pte Ltd"

        # --- 2. Key-Value Regex Extractions ---
        m = re.search(r"INVOICE\s*NO\s*:\s*([A-Z0-9\-]+)", full_p1_text, re.I)
        if m: invoice_no = m.group(1).strip()

        m = re.search(r"INVOICE\s*DATE\s*:\s*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", full_p1_text, re.I)
        if m: invoice_date = m.group(1).strip()

        m = re.search(r"DO\s*NO\s*:\s*([A-Z0-9\-]+)", full_p1_text, re.I)
        if m: do_no = m.group(1).strip()
        elif invoice_no: do_no = invoice_no

        m = re.search(r"DELIVERY\s*DATE\s*:\s*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", full_p1_text, re.I)
        if m: delivery_date = m.group(1).strip()
        elif invoice_date: delivery_date = invoice_date

        m = re.search(r"ORDER\s*NO\s*:\s*([A-Z0-9\-]+)", full_p1_text, re.I)
        if m: order_no = m.group(1).strip()

        m = re.search(r"ORDER\s*DATE\s*:\s*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", full_p1_text, re.I)
        if m: order_date = m.group(1).strip()

        m = re.search(r"PAYMENT\s*DUE\s*:\s*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", full_p1_text, re.I)
        if m: payment_due = m.group(1).strip()

        m = re.search(r"CUSTOMER\s*NO\s*:\s*([A-Z0-9\-]+)", full_p1_text, re.I)
        if m: customer_no = m.group(1).strip()
        else: customer_no = "CS"

        m = re.search(r"CURRENCY\s*:\s*([A-Z]{3})", full_p1_text, re.I)
        if m: currency = m.group(1).strip()

        # --- 3. Line Item Parsing across all pages ---
        for page in pdf.pages:
            text = page.extract_text(layout=False) or ""
            lines = text.split("\n")

            normalized_lines = []
            for line in lines:
                line_str = line.strip()
                if not line_str:
                    continue
                if re.match(r"^\d+\s+\d{7,8}\s+\d+", line_str):
                    normalized_lines.append(line_str)
                elif normalized_lines and not re.match(r"^(Page|REMARKS|GROSS|ADD GST|AMOUNT|BCRS|\*|SOLD|DELIVERED|INVOICE|DO|ORDER|TAX|NO\b)", line_str, re.I):
                    normalized_lines[-1] = normalized_lines[-1] + " " + line_str
                else:
                    normalized_lines.append(line_str)

            full_page_content = "\n".join(normalized_lines)

            for match in row_pattern.finditer(full_page_content):
                no, item_code, cust_code, desc, size, pack, qty, price, amt, bcrs = match.groups()

                all_rows.append({
                    "Sold To": sold_to,
                    "Delivered To": delivered_to,
                    "Invoice No": invoice_no,
                    "Invoice Date": invoice_date,
                    "DO No": do_no,
                    "Delivery Date": delivery_date,
                    "Order No": order_no,
                    "Order Date": order_date,
                    "Payment Due": payment_due,
                    "Customer No": customer_no,
                    "Currency": currency,
                    "Seller Name": seller_name,
                    "Seller Address": seller_address,
                    "Biz Reg No": biz_reg_no,
                    "GST Reg No": gst_reg_no,
                    "Line No": int(no),
                    "Item Code": item_code,
                    "Cust Item Code": cust_code,
                    "Description": desc.strip(),
                    "Size": size,
                    "Order Pack": int(pack),
                    "Qty": float(qty.replace(",", "")),
                    "Qty Price": float(price.replace(",", "")),
                    "Amount": float(amt.replace(",", "")),
                    "BCRS Deposit": float(bcrs.replace(",", "")),
                    "Source File": filename
                })

    return all_rows
