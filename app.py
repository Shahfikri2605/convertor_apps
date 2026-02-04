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
import tfp_processor


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
    st.title("🤖 Zenxin Data Extractor")

    if "master_data" not in st.session_state:
        st.session_state.master_data =[]

    if "qr_data" not in st.session_state:
        st.session_state.qr_data = None

    # --- SIDEBAR INPUTS ---
    with st.sidebar:
        st.write(f"👤 User: **{name}**")
        authenticator.logout('Logout', 'sidebar')
        st.divider()
        st.header("Settings")
        mode = st.radio("Select Mode", ["Standard Extraction", "Invoice with QR (UUID)", "Maslee", "Aeon", "TFP/Global"])

        st.markdown("---")

        if len(st.session_state.master_data) > 0:
            st.write(f"📊 **{len(st.session_state.master_data)} rows currently loaded.**")
            if st.button("🗑️ Clear All Data", type="secondary"):
                st.session_state.master_data =[]
                st.rerun()
        st.markdown("---")

        if mode == "Standard Extraction":
            fields = st.text_area(
                "Fields to Extract", 
                value="E.g Invoice No, Date, Description, Quantity, Total Amount",
                height=100
            )
            force_ocr = st.checkbox("Force Vision Mode", help="Use for scans/images")

    # --- MAIN LOGIC ---
    uploaded_files = st.file_uploader("Choose a PDF file", type="pdf",accept_multiple_files=True)

    if uploaded_files is not None:
        
        # === MODE 1: QR INVOICE (NEW LOGIC) ===
        if mode == "Invoice with QR (UUID)":
            st.info("ℹ️ Mode: Invoice with QR (Scans QR -> LHDN UUID).")
            
            if st.button("Extract Data (QR Mode)", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
              
                for i, file_obj in enumerate(uploaded_files):
                    status_text.text(f"Processing file {i+1}/{len(uploaded_files)}: {file_obj.name}...")
                    
                    try:
                        
                        rows = qr_invoices.process_single_invoice(
                            file_obj.getvalue(), 
                            file_obj.name, 
                            GENAI_API_KEY
                        )
                        
                        if rows:
                            st.session_state.master_data.extend(rows)
                        else:
                            st.error(f"Failed to extract: {file_obj.name}")
                            
                    except Exception as e:
                        st.error(f"Error on {file_obj.name}: {e}")
                    
                    progress_bar.progress((i+1)/len(uploaded_files))
                
                status_text.text("✅ Batch processing complete!")
                st.rerun()
        
        elif mode == "TFP/Global":
            st.info("ℹ️ Mode: TFP Retail / Global Report Extraction (Specific Format).")
            
            if st.button("Extract TFP Data", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, file_obj in enumerate(uploaded_files):
                    status_text.text(f"Processing {file_obj.name}...")
                    
                    # Call the new function
                    rows = tfp_processor.process_tfp_pdf(file_obj, file_obj.name)
                    
                    if rows:
                        st.session_state.master_data.extend(rows)
                    else:
                        st.warning(f"No data found in {file_obj.name}")
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                
                status_text.text("✅ TFP Processing Complete!")
                st.rerun()


        # === MODE 2: STANDARD EXTRACTION ===
        else:
            st.info("ℹ️ Mode: Standard AI Extraction")
            
            if st.button("Extract Data", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
             
                for i, file_obj in enumerate(uploaded_files):
                    status_text.text(f"Processing file {i+1}/{len(uploaded_files)}: {file_obj.name}...")
                    
                    try:
                        # 1. Read File
                        bytes_data = file_obj.getvalue()
                        
                        # 2. Hybrid Logic
                        raw_text = ""
                        use_vision = force_ocr
                        
                        if not use_vision:
                            try:
                                with pdfplumber.open(file_obj) as pdf:
                                    for page in pdf.pages[:5]:
                                        text = page.extract_text()
                                        if text: raw_text += text + "\n"
                            except:
                                pass
                            
                            if len(raw_text) < 50:
                                use_vision = True
                        
                        # 3. AI Processing
                        prompt = f"""
                        Act as a Data Analyst. Extract table. Columns: {fields}
                        Instructions: Return strictly a JSON list of objects.
                        """
                        
                        response_text = ""
                        if use_vision:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                                tmp.write(bytes_data)
                                temp_path = tmp.name
                                
                            uploaded_ref = genai.upload_file(temp_path)
                            response = model.generate_content([uploaded_ref, prompt])
                            response_text = response.text
                            os.unlink(temp_path)
                        else:
                            full_prompt = f"{prompt}\n\nSOURCE TEXT:\n---\n{raw_text}\n---"
                            response = model.generate_content(
                                full_prompt, 
                                request_options={"timeout": 600}
                            )
                            response_text = response.text

                        # 4. Parse
                        cleaned = response_text.replace("```json", "").replace("```", "").strip()
                        try:
                            data = json.loads(cleaned)
                        except:
                            start = cleaned.find('[')
                            end = cleaned.rfind(']') + 1
                            data = json.loads(cleaned[start:end])
                        
                        if data:
                            for row in data:
                                row['Source File'] = file_obj.name
                            st.session_state.master_data.extend(data)
                        else:
                            st.warning(f"No data found in {file_obj.name}")

                    except Exception as e:
                        st.error(f"Error on {file_obj.name}: {e}")
                    
                    progress_bar.progress((i+1)/len(uploaded_files))
                
                status_text.text("✅ Batch processing complete!")
                st.rerun()

    st.divider()

    # --- DISPLAY LOGIC (Same as before) ---
    if len(st.session_state.master_data) > 0:
        st.subheader(f"📊 Extracted Data ({len(st.session_state.master_data)} Rows)")
        df = pd.DataFrame(st.session_state.master_data)
        
     
        
        st.dataframe(df, use_container_width=True)
        
        # Download
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        
        st.download_button(
            label="📥 Download Excel",
            data=output.getvalue(),
            file_name="combined_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
