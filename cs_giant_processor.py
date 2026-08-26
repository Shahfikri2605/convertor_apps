import io
import re
import pypdf
import pandas as pd

def process_cs_giant_pdf(file_bytes, filename=""):
    """
    Universal extractor for all Zenxin Cold Storage & Giant Singapore Invoices.
    Supports all historical layouts:
      - With/Without 8-digit Item Code
      - With/Without BCRS Deposit column
      - All months (2025, 2026, Nov, Dec, Jan, Feb, Mar, Apr, Jul, etc.)
    """
    all_rows = []

    seller_name = "Zenxin Agri-Organic Food Pte Ltd"
    seller_address = "Blk14 Wholesale Centre #01-25, SINGAPORE, 110014"
    biz_reg_no = "200616582M"
    gst_reg_no = "200616582M"
    sold_to = "COLD STORAGE SINGAPORE (1983) PTE LTD"
    delivered_to = "Cold Storage Singapore (1983) Pte Ltd"
    invoice_no = ""
    invoice_date = ""
    do_no = ""
    delivery_date = ""
    order_no = ""
    order_date = ""
    payment_due = ""
    customer_no = "CS"
    currency = "SGD"

    # Read PDF using pypdf
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    full_text_list = []

    for i, page in enumerate(reader.pages):
        page_txt = page.extract_text() or ""
        full_text_list.append(page_txt)

        # Parse header metadata from Page 1
        if i == 0:
            m_inv = re.search(r"SO\d{2}-\d{7}", page_txt)
            if m_inv:
                invoice_no = m_inv.group(0).strip()

            m_date = re.search(r"(\d{1,2}-[A-Za-z]{3}-20\d{2})", page_txt)
            if m_date:
                invoice_date = m_date.group(1).strip()

            m_do = re.search(r"DO\s*NO\s*:\s*([A-Z0-9\-]+)", page_txt, re.I)
            if m_do:
                do_no = m_do.group(1).strip()
            elif invoice_no:
                do_no = invoice_no

            m_order = re.search(r"(?:ORDER\s*NO\s*:\s*|ORDER\s*:\s*|NO\s*:\s*)([A-Z0-9]{8,12})", page_txt, re.I)
            if m_order:
                order_no = m_order.group(1).strip()
            else:
                m_ord_fallback = re.search(r"(CON\d+|05\d+)", page_txt)
                if m_ord_fallback:
                    order_no = m_ord_fallback.group(1).strip()

            m_ord_date = re.search(r"ORDER\s*DATE\s*:\s*(\d{1,2}-[A-Za-z]{3}-20\d{2})", page_txt, re.I)
            if m_ord_date:
                order_date = m_ord_date.group(1).strip()
            elif invoice_date:
                order_date = invoice_date

            delivery_date = invoice_date

            if "SGD" in page_txt:
                currency = "SGD"

    full_pdf_text = "\n".join(full_text_list)

    # Universal Line Item Pattern matching all layouts and column variants
    row_pattern = re.compile(
        r"(?:(?P<item_code>\d{8})\s*)?"               # Optional 8-digit Item Code
        r"(?P<cust_code>\d{7})\s+"                    # 7-digit Cust Item Code
        r"(?P<line_no>\d+)\s+"                        # Line No
        r"(?P<pack>\d+)\s+"                           # Order Pack
        r"(?P<desc>.*?)\s+"                           # Description
        r"(?P<amt>[\d,]+\.\d{2})\s+"                  # Total Line Amount
        r"(?P<price>[\d,]+\.\d{4,9})\s*"              # Unit Price (4-9 decimals)
        r"(?P<size>[A-Za-z0-9/]{2,5})?\s+"            # Optional UOM/Size (PK, EA, BO, KGM, 00000)
        r"(?P<qty>\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*"  # Quantity
        r"(?P<bcrs>0\.00)?"                           # Optional BCRS (present in newer PDFs)
    )

    matches = list(row_pattern.finditer(full_pdf_text))

    for m in matches:
        item_code = m.group("item_code") or ""
        cust_code = m.group("cust_code")
        line_no = int(m.group("line_no"))
        pack = int(m.group("pack"))
        desc = m.group("desc").strip()
        amt = float(m.group("amt").replace(",", ""))
        price = float(m.group("price").replace(",", ""))
        size = m.group("size") or ""
        qty = float(m.group("qty").replace(",", ""))
        bcrs = float(m.group("bcrs").replace(",", "")) if m.group("bcrs") else 0.0

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
            "Line No": line_no,
            "Item Code": item_code,
            "Cust Item Code": cust_code,
            "Description": desc,
            "Size": size,
            "Order Pack": pack,
            "Qty": qty,
            "Qty Price": price,
            "Amount": amt,
            "BCRS Deposit": bcrs,
            "Source File": filename
        })

    return all_rows
