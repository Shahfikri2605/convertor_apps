import pandas as pd
import re
from io import BytesIO

def process_global_excel(uploaded_files):
    """
    Cleans the 'Global Consignment Report' Excel/CSV.
    Extracts 'Store' into a 'Location' column and separates 'SKU NO'.
    """
    all_rows = []

    for file_obj in uploaded_files:
        try:
            # 1. Read the file without headers (so we can scan row by row)
            if file_obj.name.endswith('.csv'):
                df_raw = pd.read_csv(file_obj, header=None, dtype=str)
            else:
                df_raw = pd.read_excel(file_obj, header=None, dtype=str)

            current_location = "Unknown Location"
            
            # 2. Iterate through rows
            for index, row in df_raw.iterrows():
                cell_0 = str(row[0]).strip() if pd.notna(row[0]) else ""
                
                # Check if this row declares a new Store/Location
                if cell_0.startswith("Store :"):
                    current_location = cell_0.replace("Store :", "").strip()
                    continue
                
                # Check if this is a Data Row (Starts with a Date like 01/11/2025)
                if re.match(r"\d{2}/\d{2}/\d{4}", cell_0):
                    item_str = str(row[1]) if pd.notna(row[1]) else ""
                    
                    # Extract SKU No (Text before the '|')
                    sku_no = ""
                    if "|" in item_str:
                        sku_no = item_str.split("|")[0].strip()
                    else:
                        sku_no = item_str.strip()

                    # Safe float converter for numbers
                    def to_float(val):
                        try:
                            return float(str(val).replace(',', '').strip())
                        except:
                            return 0.0

                    # Append cleaned row based on the raw file structure
                    all_rows.append({
                        "Location": current_location,
                        "Sales Date": cell_0,
                        "SKU NO": sku_no,
                        "Item": item_str,
                        "Qty Sold": to_float(row[2]),
                        "Gross Amount": to_float(row[3]),
                        "Discount": to_float(row[4]),
                        "Net Excl Tax": to_float(row[6]),
                        "Tax Amount": to_float(row[8]),   
                        "Net Incl Tax": to_float(row[9])  
                    })

        except Exception as e:
            print(f"Error reading {file_obj.name}: {e}")

    if not all_rows:
        return None, None

    # 3. Create Clean DataFrame
    df_clean = pd.DataFrame(all_rows)

    # 4. Save to Excel format
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_clean.to_excel(writer, index=False, sheet_name='Sheet1')
        
        # Auto-adjust column widths for better viewing
        worksheet = writer.sheets['Sheet1']
        for idx, col in enumerate(df_clean.columns):
            max_len = max(df_clean[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(idx, idx, max_len)

    return output, df_clean
