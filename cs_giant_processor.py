import io
import re
import pdfplumber
import pandas as pd


def process_cs_giant_pdf(file_bytes, filename=""):
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

    # Recognised packaging-size / unit tokens
    units = ["PK", "EA", "BO", "KGM", "BTL", "SET", "CAN", "BAG",
             "TIN", "PCS", "PC", "CTN", "BOX", "KG", "G", "ML", "L"]
    unit_re = re.compile(r"\b(" + "|".join(units) + r")\b", re.I)

    # Recognised weight / volume tokens inside descriptions, e.g. 250G, 500G, 1KG, 200G
    weight_re = re.compile(r"\b(\d+(?:\.\d+)?)\s*(KG|G|ML|L|KGM)\b", re.I)

    def parse_size_and_desc(raw_desc, raw_size):
        """Return (clean_description, size_string)."""
        size_parts = []

        # 1. Grab from the dedicated SIZE column (e.g. PK, EA, BO, KGM)
        if raw_size:
            s = raw_size.strip().upper()
            if s:
                size_parts.append(s)

        desc = raw_desc or ""

        # 2. Extract a packaging size token from the description if present
        u_match = unit_re.search(desc)
        if u_match:
            tok = u_match.group(1).upper()
            if tok not in size_parts:
                size_parts.append(tok)
            desc = unit_re.sub(" ", desc)

        # 3. Extract a weight/volume token from the description, e.g. "250G", "1KG"
        w_match = weight_re.search(desc)
        if w_match:
            weight = f"{w_match.group(1)}{w_match.group(2).upper()}"
            if weight not in size_parts:
                size_parts.append(weight)
            desc = weight_re.sub(" ", desc)

        desc = re.sub(r"\s+", " ", desc).strip(" .*-_")
        size = " ".join(size_parts).strip()
        return desc, size

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        if len(pdf.pages) == 0:
            return []

        # ---------- 1. Header extraction from Page 1 ----------
        p1_txt = pdf.pages[0].extract_text() or ""

        m_inv = re.search(r"SO\d{2}-\d{7}", p1_txt)
        if m_inv:
            invoice_no = m_inv.group(0).strip()

        m_date = re.search(r"(\d{1,2}-[A-Za-z]{3}-20\d{2})", p1_txt)
        if m_date:
            invoice_date = m_date.group(1).strip()

        m_do = re.search(r"DO\s*NO\s*:\s*([A-Z0-9\-]+)", p1_txt, re.I)
        if m_do:
            do_no = m_do.group(1).strip()
        elif invoice_no:
            do_no = invoice_no

        m_order = re.search(
            r"(?:ORDER\s*NO\s*:\s*|ORDER\s*:\s*|NO\s*:\s*)([A-Z0-9]{8,12})",
            p1_txt, re.I
        )
        if m_order:
            order_no = m_order.group(1).strip()
        else:
            m_ord_fallback = re.search(r"\b(CON\d+|05\d{8})\b", p1_txt)
            if m_ord_fallback:
                order_no = m_ord_fallback.group(1).strip()

        m_ord_date = re.search(
            r"ORDER\s*DATE\s*:\s*(\d{1,2}-[A-Za-z]{3}-20\d{2})", p1_txt, re.I
        )
        if m_ord_date:
            order_date = m_ord_date.group(1).strip()
        elif invoice_date:
            order_date = invoice_date

        delivery_date = invoice_date

        # ---------- 2. Page-by-page table extraction ----------
        for page in pdf.pages:
            tables = page.extract_tables()

            for table in tables:
                # Detect the column layout from the header row
                header = None
                for hrow in table[:3]:
                    joined = " ".join(str(c) for c in hrow if c).upper()
                    if "DESCRIPTION" in joined and "QTY" in joined:
                        header = [str(c).strip().upper() if c else "" for c in hrow]
                        break

                for row in table:
                    if not row:
                        continue
                    cells = [str(c).strip() if c else "" for c in row]

                    # Skip the header row itself
                    if any("DESCRIPTION" in c.upper() for c in cells):
                        continue

                    # First cell must be a line number (1-3 digits)
                    if not cells[0].isdigit():
                        continue

                    line_no = int(cells[0])
                    if line_no < 1 or line_no > 500:
                        continue

                    # Map columns by position (matches the header layout)
                    item_code = cells[1] if len(cells) > 1 else ""
                    cust_code = cells[2] if len(cells) > 2 else ""
                    desc_raw = cells[3] if len(cells) > 3 else ""
                    size_raw = cells[4] if len(cells) > 4 else ""
                    pack_raw = cells[5] if len(cells) > 5 else "1"
                    qty_raw = cells[6] if len(cells) > 6 else "0"
                    price_raw = cells[7] if len(cells) > 7 else "0"
                    amt_raw = cells[8] if len(cells) > 8 else "0"

                    # ---- Parse size + description ----
                    desc, size = parse_size_and_desc(desc_raw, size_raw)
                    if not desc or desc.isdigit():
                        continue

                    # ---- Numeric parsing ----
                    try:
                        pack = int(float(pack_raw)) if pack_raw else 1
                    except ValueError:
                        pack = 1

                    try:
                        qty = float(qty_raw.replace(",", "")) if qty_raw else 0.0
                    except ValueError:
                        qty = 0.0

                    try:
                        price = float(price_raw.replace(",", ".")) if price_raw else 0.0
                    except ValueError:
                        price = 0.0

                    try:
                        amt = float(amt_raw.replace(",", "")) if amt_raw else 0.0
                    except ValueError:
                        amt = 0.0

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
                        "Size": size,                       # <-- SIZE EXTRACTED HERE
                        "Order Pack": pack,
                        "Qty": qty,
                        "Qty Price": price,
                        "Amount": amt,
                        "BCRS Deposit": 0.0,
                        "Source File": filename,
                    })

        # ---------- 3. Fallback if extract_tables() found nothing ----------
        if not all_rows:
            for page in pdf.pages:
                page_txt = page.extract_text() or ""
                clean = re.split(r"TAX\s+INVOICE", page_txt, flags=re.I)[-1]
                clean = re.split(r"REMARKS\s*:", clean, flags=re.I)[0]
                clean = re.sub(r"Page\s+\d+\s+of\s+\d+", "", clean, flags=re.I)

                row_pattern = re.compile(
                    r"(?P<line_no>\b\d{1,3}\b)\s+"
                    r"(?:(?P<zenxin_code>\d{8})\s+)?"
                    r"(?P<cust_code>\d{6,7})\s+"
                    r"(?P<middle>.*?)\s+"
                    r"(?P<n1>[\d,]+(?:\.\d+)?)\s+"
                    r"(?P<n2>[\d,]+(?:\.\d+)?)\s+"
                    r"(?P<price>[\d,]+[.,]\d{2,4})\s+"
                    r"(?P<amt>[\d,]+\.\d{2})",
                    re.DOTALL,
                )

                for m in row_pattern.finditer(clean):
                    line_no = int(m.group("line_no"))
                    zenxin_code = m.group("zenxin_code") or ""
                    cust_code = m.group("cust_code")
                    middle = m.group("middle").strip()

                    n1 = float(m.group("n1").replace(",", ""))
                    n2 = float(m.group("n2").replace(",", ""))
                    price = float(m.group("price").replace(",", "."))
                    amt = float(m.group("amt").replace(",", ""))

                    if n1 <= 10 and n1.is_integer() and (n2 > 10 or not n2.is_integer()):
                        pack, qty = int(n1), n2
                    elif n2 <= 10 and n2.is_integer() and (n1 > 10 or not n1.is_integer()):
                        pack, qty = int(n2), n1
                    else:
                        pack = int(n1) if n1.is_integer() else 1
                        qty = n2

                    desc, size = parse_size_and_desc(middle, "")

                    if not desc:
                        continue

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
                        "Item Code": zenxin_code,
                        "Cust Item Code": cust_code,
                        "Description": desc,
                        "Size": size,
                        "Order Pack": pack,
                        "Qty": qty,
                        "Qty Price": price,
                        "Amount": amt,
                        "BCRS Deposit": 0.0,
                        "Source File": filename,
                    })

    # ---------- 4. De-duplicate & sort ----------
    seen = set()
    deduped = []
    for row in sorted(all_rows, key=lambda x: x["Line No"]):
        if row["Line No"] not in seen:
            seen.add(row["Line No"])
            deduped.append(row)

    return deduped
