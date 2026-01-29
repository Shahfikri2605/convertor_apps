import streamlit as st
import pdfplumber
import pandas as pd
import google.generativeai as genai
import json
import tempfile
import os
from io import BytesIO
import qr_invoices
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURATION ---
# ⚠️ PASTE YOUR API KEY HERE
GENAI_API_KEY = st.secrets["Gen_API"]["API_KEY"]

genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview')

@st.cache_resource
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    return gspread.authorize(creds)

def make_url(sheet_id):
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

@st.cache_data(ttl=600)
def load_google_sheet(url, sheet_name=0):
    try:
        client = get_gspread_client()
        sheet = client.open_by_url(url)
        if isinstance(sheet_name, str): worksheet = sheet.worksheet(sheet_name)
        else: worksheet = sheet.get_worksheet(sheet_name)
        data = worksheet.get_all_values()
        return pd.DataFrame(data)
    except Exception as e: 
        print(f"Error loading {sheet_name}: {e}")
        return None

def main_app_interface(authenticator, name, permissions):
# --- PAGE SETUP ---
    st.set_page_config(page_title="Zenxin Data Extractor", page_icon="🤖", layout="wide")
    st.title("🤖 Zenxin Data Extractor")

    if "qr_data" not in st.session_state:
        st.session_state.qr_data = None

    # --- SIDEBAR INPUTS ---
    with st.sidebar:
        st.write(f"👤 User: **{name}**")
        authenticator.logout('Logout', 'sidebar')
        st.divider()
        st.header("Settings")
        mode = st.radio("Select Mode", ["Standard Extraction", "Invoice with QR (UUID)"])

        st.markdown("---")
        if mode == "Standard Extraction":
            fields = st.text_area(
                "Fields to Extract", 
                value="Invoice No, Date, Description, Quantity, Total Amount",
                height=100
            )
            force_ocr = st.checkbox("Force Vision Mode", help="Use for scans/images")

    # --- MAIN LOGIC ---
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

    if uploaded_file is not None:
        
        # === MODE 1: QR INVOICE (NEW LOGIC) ===
        if mode == "Invoice with QR (UUID)":
            st.info("ℹ️ Mode: Invoice with QR. This will scan the QR code to fetch the UUID from LHDN website.")
            
            if st.button("Extract Data (QR Mode)", type="primary"):
                with st.spinner("Scanning QR, visiting LHDN, and processing AI..."):
                    try:
                        # Call the function from your new file
                        rows = qr_invoices.process_single_invoice(
                            uploaded_file.getvalue(), 
                            uploaded_file.name, 
                            GENAI_API_KEY
                        )
                        
                        if rows:
                            st.session_state.qr_data = rows
                            st.success("✅ Extraction Complete!")
                        else:
                            st.error("Failed to extract data.")
                            
                    except Exception as e:
                        st.error(f"Error: {e}")

            # Display Results
            if st.session_state.qr_data:
                df = pd.DataFrame(st.session_state.qr_data)
                
                # Reorder columns for clean display
                cols = ["FileName", "Bill To", "Invoice No.", "Invoice Date", "UUID", "Total MYR"]
                
                # Filter columns that actually exist in the data
                existing_cols = [c for c in cols if c in df.columns]
                df = df[existing_cols]

                st.dataframe(df, use_container_width=True)

                # Excel Download
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False)
                
                st.download_button(
                    label="📥 Download Excel",
                    data=output.getvalue(),
                    file_name="qr_extracted_data.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    else:
        st.write("Standard extraction ")
        if st.button("Extract Data", type="primary"):
            with st.spinner("Processing... (This may take a moment)"):
                try:
                    # 1. Read File
                    bytes_data = uploaded_file.getvalue()
                    
                    # 2. Hybrid Logic (Text vs Vision)
                    raw_text = ""
                    use_vision = force_ocr
                    
                    if not use_vision:
                        # Try reading text first
                        with pdfplumber.open(uploaded_file) as pdf:
                            for page in pdf.pages[:5]:
                                text = page.extract_text()
                                if text: raw_text += text + "\n"
                        
                        if len(raw_text) < 50:
                            use_vision = True
                            st.info("ℹ️ Low text detected. Switching to AI Vision mode automatically.")

                    # 3. AI Processing
                    prompt = f"""
                    Act as a Data Analyst.
                    Task: Extract a table from the document.
                    Columns needed: {fields}
                    Instructions:
                    - Extract all rows.
                    - Map columns to requested names.
                    - Return strictly a JSON list of objects.
                    """
                    
                    response_text = ""
                    
                    if use_vision:
                        # Save temp file for upload
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(bytes_data)
                            temp_path = tmp.name
                            
                        uploaded_ref = genai.upload_file(temp_path)
                        response = model.generate_content([uploaded_ref, prompt])
                        response_text = response.text
                        os.unlink(temp_path) # Cleanup
                    else:
                        full_prompt = f"{prompt}\n\nSOURCE TEXT:\n---\n{raw_text}\n---"
                        response = model.generate_content(
                            full_prompt,
                            request_options={"timeout": 600}
                        )
                        response_text = response.text

                    # 4. Clean & Parse JSON
                    cleaned = response_text.replace("```json", "").replace("```", "").strip()
                    
                    try:
                        data = json.loads(cleaned)
                    except:
                        # Fallback repair
                        start = cleaned.find('[')
                        end = cleaned.rfind(']') + 1
                        data = json.loads(cleaned[start:end])
                    
                    # 5. Display Result
                    if data:
                        df = pd.DataFrame(data)
                        st.success(f"✅ Extracted {len(data)} rows!")
                        st.dataframe(df, use_container_width=True)
                        
                        # 6. Excel Download Button
                        # Convert DF to Excel in memory
                        output = BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False)
                        excel_data = output.getvalue()
                        
                        st.download_button(
                            label="📥 Download Excel",
                            data=excel_data,
                            file_name="extracted_data.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    else:
                        st.error("AI returned empty data. Try refining your fields.")

                except Exception as e:
                    st.error(f"Error: {e}")

