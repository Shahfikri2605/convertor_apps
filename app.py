#1
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
import maslee_processor
import aeon_processor  
import urban_processor
import jaya_processor
import isetan_processor
import kastam_processor
import boost
import pbb_processor
import data_cleaner
import lazada_processor
import sales_report

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
        mode = st.radio("Select Mode", ["Standard Extraction", "Invoice with QR (UUID)", "Maslee", "Aeon Sales & Commission", "TFP/Global", "Urban (AI)", "Jaya Grocer (AI)", "iSetan (AI)","Kastam (AI)","Boost","Public Bank (PBB)","Data Cleaner (Excel)","Lazada Payout Combiner", "Zenxin Sales Report"], index=0)

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
                with st.spinner("Processing large file... Please wait, do not refresh."):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    for i, file_obj in enumerate(uploaded_files):
                        status_text.text(f"Processing {file_obj.name}...")
                        
                        # Call the new function
                        rows = tfp_processor.process_tfp_pdf(file_obj.getvalue(), file_obj.name)
                        
                        if rows:
                            st.session_state.master_data.extend(rows)
                        else:
                            st.warning(f"No data found in {file_obj.name}")
                        
                        progress_bar.progress((i + 1) / len(uploaded_files))
                    
                    status_text.text("✅ TFP Processing Complete!")
                    st.rerun()

        elif mode == "Maslee":
            st.info("ℹ️ Mode: Maslee/Retail (Regex + AI Fallback).")
            
            if st.button("Extract Maslee Data", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, file_obj in enumerate(uploaded_files):
                    status_text.text(f"Processing {file_obj.name}...")
                    
                    # Call the new function
                    rows = maslee_processor.extract_data_from_pdf(
                        file_obj.getvalue(), 
                        file_obj.name,
                        GENAI_API_KEY
                    )
                    
                    if rows:
                        st.session_state.master_data.extend(rows)
                    else:
                        st.warning(f"No data found in {file_obj.name}")
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                
                status_text.text("✅ Maslee Processing Complete!")
                st.rerun()
        elif mode =="Aeon Sales & Commission":
            st.info("ℹ️ Mode: AEON (Auto-aggregates Invoices by Store). Output has multiple sheets.")
            
            if st.button("Process AEON Files", type="primary"):
                all_dfs = []
                file_summary = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # 1. Extract Raw Data from all files
                for i, file_obj in enumerate(uploaded_files):
                    status_text.text(f"Scanning {file_obj.name}...")
                    try:
                        df = aeon_processor.extract_aeon_raw_data(file_obj.getvalue(), file_obj.name)
                        if not df.empty:
                            df['SOURCE_FILE'] = file_obj.name
                            all_dfs.append(df)
                            file_summary.append((file_obj.name, len(df)))
                        else:
                            file_summary.append((file_obj.name, 0))
                    except Exception as e:
                        file_summary.append((file_obj.name, f"Error: {e}"))
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))

                # 2. Process & Generate Excel
                if all_dfs:
                    combined_df = pd.concat(all_dfs, ignore_index=True)
                    excel_data, preview_df = aeon_processor.generate_aeon_excel(combined_df, file_summary)
                    
                    st.success("✅ AEON Processing Complete!")
                    
                    # Display Preview (Just the Invoice Sheet)
                    if not preview_df.empty:
                        st.subheader("Preview (INVOICE Sheet)")
                        st.dataframe(preview_df, use_container_width=True)
                    
                    # Download Button
                    st.download_button(
                        label="📥 Download AEON Report (Multi-Sheet)",
                        data=excel_data.getvalue(),
                        file_name="AEON_Consolidated_Report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.error("No valid AEON data found in uploaded files.")
        elif mode == "Urban (AI)":
            st.info("ℹ️ Mode: Urban Grocery (Full AI Scan + Cleaning).")

            if st.button("Extract Urban Data", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, file_obj in enumerate(uploaded_files):
                    status_text.text(f"Uploading & Scanning {file_obj.name} with AI ..")

                    rows = urban_processor.process_urban_pdf(
                        file_obj.getvalue(),
                        file_obj.name,
                        GENAI_API_KEY
                    )

                    if rows:
                        st.session_state.master_data.extend(rows)
                    else:
                        st.warning(f"No data found in {file_obj.name}")
                    progress_bar.progress((i+1)/len(uploaded_files))
                
                status_text.text("✅ Urban Processing Complete!")
                st.rerun()
        elif mode == "Jaya Grocer (AI)":
            st.info("ℹ️ Mode: Jaya Grocer (ZA02 Consignment). Includes Auto-Total Calculation.")
            
            if st.button("Extract Jaya Data", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, file_obj in enumerate(uploaded_files):
                    status_text.text(f"Processing {file_obj.name}...")
                    
                    # Call the new function
                    rows = jaya_processor.process_jaya_pdf(
                        file_obj.getvalue(), 
                        file_obj.name,
                        GENAI_API_KEY
                    )
                    
                    if rows:
                        st.session_state.master_data.extend(rows)
                    else:
                        st.warning(f"No data found in {file_obj.name}")
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                
                status_text.text("✅ Jaya Processing Complete!")
                st.rerun()
        elif mode == "iSetan (AI)":
            st.info("ℹ️ Mode: iSetan (Extracts Item Code, Name, Qty, Unit Price).")
            
            if st.button("Extract iSetan Data", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, file_obj in enumerate(uploaded_files):
                    status_text.text(f"Processing {file_obj.name}...")
                    
                    # Call the new function
                    rows = isetan_processor.process_isetan_pdf(
                        file_obj.getvalue(), 
                        file_obj.name,
                        GENAI_API_KEY
                    )
                    
                    if rows:
                        st.session_state.master_data.extend(rows)
                    else:
                        st.warning(f"No data found in {file_obj.name}")
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                
                status_text.text("✅ iSetan Processing Complete!")
                st.rerun()
        elif mode == "Kastam (AI)":
            st.info("ℹ️ Mode: Kastam (Page-by-Page Scan). SLOW but Safe.")
            
            if st.button("Process Kastam", type="primary"):
                progress_bar = st.progress(0)
            
                for i, file_obj in enumerate(uploaded_files):
                    st.write(f"🔍 Analyzing {file_obj.name}...")
                    
                    # 1. Extraction
                    rows = kastam_processor.process_jsp_invoice(
                        file_obj.getvalue(), 
                        file_obj.name, 
                        GENAI_API_KEY
                    )
                    
                    if rows:
                        df_temp = pd.DataFrame(rows)

                        # --- FIX START ---
                        # Convert 'Amount' to numeric, forcing errors to NaN (which we then fill with 0)
                        df_temp["Amount"] = pd.to_numeric(df_temp["Amount"], errors='coerce').fillna(0)
                        # --- FIX END ---
                                    
                        # Now this sum will definitely be a float
                        total_extracted = df_temp["Amount"].sum()
                        expected_total = 5618.00 
                                    
                        # This comparison will now work
                        if abs(total_extracted - expected_total) < 0.05:
                            st.success(f"✅ {file_obj.name}: Verified! Sum matches {expected_total}.")
                        else:
                            st.warning(f"⚠️ {file_obj.name}: Accuracy Warning! Extracted sum: {total_extracted:.2f} (Expected: {expected_total})")
                        
                        # Check Row Count: Should be 226 [cite: 255]
                        if len(rows) == 226:
                            st.success(f"✅ Row count verified: 226 items found.")
                        else:
                            st.info(f"ℹ️ Found {len(rows)} rows. (Expected 226 for this specific sample)")

                        st.session_state.master_data.extend(rows)
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                st.rerun()
        elif mode == "Boost":
            st.info("ℹ️ Mode: Boost (Combines CSVs + Formats Table).")

            # --- Boost Specific Inputs ---
            col1, col2 = st.columns(2)
            with col1:
                report_month = st.text_input("Report Month", value="JAN 2026")
                outlet_name = st.text_input("Outlet Name", value="CHENG OUTLET")
            with col2:
                company_name = st.text_input("Company Name", value="ZENXIN AGRI-ORGANIC FOOD (MELAKA) SDN BHD")
                bank_account = st.text_input("Bank Details", value="OCBC - 715-110808-8")
            
            # --- Override File Uploader for CSV ---
            # Note: The main uploader is for PDF. We can show a second one or tell user to use PDF uploader (if we change allowed types).
            # BETTER UX: Add a specific CSV uploader inside this block.
            boost_files = st.file_uploader("Choose Boost CSV files", accept_multiple_files=True, type=['csv'], key="boost_uploader")

            if boost_files:
                if st.button("Process Boost Files", type="primary"):
                    try:
                        # Call Processor
                        excel_data, preview_df = boost.process_boost_files(
                            boost_files, 
                            report_month, 
                            outlet_name, 
                            company_name, 
                            bank_account
                        )
                        
                        if excel_data:
                            st.success("✅ Boost Processing Complete!")
                            
                            st.subheader("Preview Data")
                            st.dataframe(preview_df.head(), use_container_width=True)
                            
                            file_name = f"Boost_Table_{report_month.replace(' ', '_')}.xlsx"
                            
                            st.download_button(
                                label="📥 Download Formatted Excel",
                                data=excel_data.getvalue(),
                                file_name=file_name,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                        else:
                            st.error("No valid transactions found in the uploaded CSVs.")
                            
                    except Exception as e:
                        st.error(f"Error: {e}")
        elif mode == "Public Bank (PBB)":
            #st.info("ℹ️ Mode: Public Bank (Combines Multiple PDFs -> Formats like Boost Table).")

            # --- Inputs ---
            col1, col2 = st.columns(2)
            with col1:
                report_month = st.text_input("Report Month", value="DEC 2025")
                outlet_name = st.text_input("Outlet Name", value="CHENG OUTLET")
            with col2:
                company_name = st.text_input("Company Name", value="ZENXIN AGRI-ORGANIC FOOD (MELAKA) SDN BHD")
                bank_account = st.text_input("Bank Details", value="OCBC - 715-110808-8")
            
            # Use main uploader
            if uploaded_files:
                if st.button("Process Public Bank Files", type="primary"):
                    try:
                        # FIX: Pass 'uploaded_files' (the whole list), not just one file
                        excel_data, preview_df = pbb_processor.process_publicbank_files(
                            uploaded_files,
                            report_month,
                            outlet_name,
                            company_name,
                            bank_account
                        )
                        
                        if excel_data:
                            st.success(f"✅ Combined {len(uploaded_files)} files successfully!")
                            
                            st.subheader(f"Preview Data ({len(preview_df)} transactions)")
                            st.dataframe(preview_df, use_container_width=True)
                            
                            file_name = f"PublicBank_Table_{report_month.replace(' ', '_')}.xlsx"
                            
                            st.download_button(
                                label="📥 Download Formatted Excel",
                                data=excel_data.getvalue(),
                                file_name=file_name,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                        else:
                            st.error("No valid transactions found.")
                            
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.warning("Please upload PDF files above.")
        elif mode == "Data Cleaner (Excel)":
            st.header("🧹 Data Cleaning Tool")
            st.write("Upload raw data files (CSV/Excel) to clean and merge them.")
            
           # Uploader specifically for Excel/CSV
            global_files = st.file_uploader(
                "Upload Global Consignment Reports (Excel or CSV)", 
                accept_multiple_files=True, 
                type=['xlsx', 'xls', 'csv'],
                key="global_uploader"
            )

            if global_files:
                if st.button("Clean and Combine Reports", type="primary"):
                    with st.spinner("Cleaning data..."):
                        try:
                            # Call the Processor
                            excel_data, preview_df = data_cleaner.process_global_excel(global_files)
                            
                            if excel_data is not None:
                                st.success(f"✅ Successfully cleaned {len(preview_df)} rows!")
                                
                                # Show Preview
                                st.subheader("Preview Cleaned Data")
                                st.dataframe(preview_df.head(10), use_container_width=True)
                                
                                # Download Button
                                st.download_button(
                                    label="📥 Download Cleaned Excel",
                                    data=excel_data.getvalue(),
                                    file_name="Extracted_Global_Consignment.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                )
                            else:
                                st.error("No valid data found. Make sure the file matches the expected layout.")
                                
                        except Exception as e:
                            st.error(f"An error occurred: {e}")
            else:
                st.warning("Please upload Excel/CSV files above.")
        elif mode == "Lazada Payout Combiner":
            st.info("ℹ️ Mode: Lazada. Combines weekly CSVs, removes junk columns, and generates a Summary Report.")

            # Custom Uploader for Lazada CSVs
            lazada_files = st.file_uploader(
                "Upload Lazada Transaction CSVs (Multiple Weeks)", 
                accept_multiple_files=True, 
                type=['csv','xlsx','xls'],
                key="lazada_uploader"
            )

            if lazada_files:
                if st.button("Combine Lazada Files", type="primary"):
                    with st.spinner("Merging weekly statements..."):
                        try:
                            # Call the Processor
                            excel_data, preview_df = lazada_processor.process_lazada_files(lazada_files)
                            
                            if excel_data is not None:
                                st.success(f"✅ Successfully combined {len(lazada_files)} weekly statements!")
                                
                                # Show Preview of Raw Data
                                st.subheader(f"Preview Combined Data ({len(preview_df)} rows)")
                                st.dataframe(preview_df.head(10), use_container_width=True)
                                
                                # Download Button
                                st.download_button(
                                    label="📥 Download Lazada Monthly Report (Excel)",
                                    data=excel_data.getvalue(),
                                    file_name="Lazada_Combined_Report.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                )
                            else:
                                st.error("No valid data found in the uploaded files.")
                                
                        except Exception as e:
                            st.error(f"An error occurred: {e}")
            else:
                st.warning("Please upload Lazada CSV files above.")
        # === MODE 2: STANDARD EXTRACTION ===
        elif mode == "Zenxin Sales Report":
            st.info("ℹ️ Mode: Zenxin Sales Report. Rule-based extraction (Fast & Free).")
            
            if st.button("Extract Sales Data", type="primary"):
                progress_bar = st.progress(0)
                all_dfs = [] # Collect the full DataFrames here to preserve headers
                
                for i, file_obj in enumerate(uploaded_files):
                    st.write(f"Processing: {file_obj.name}")
                    
                    try:
                        # Call the logic directly
                        df = sales_report.process_zenxin_sales_report(file_obj.getvalue(), file_obj.name)
                        if not df.empty:
                            all_dfs.append(df)
                        else:
                            st.warning(f"No data found in {file_obj.name}")
                            
                    except Exception as e:
                        st.error(f"Error on {file_obj.name}: {e}")
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                
                if all_dfs:
                    # Combine all uploaded PDFs into one massive DataFrame
                    final_df = pd.concat(all_dfs, ignore_index=True)
                    
                    st.success("✅ Processing Complete!")
                    
                    # Show a quick preview to the user
                    st.subheader("Preview Data")
                    st.dataframe(final_df.head(15))
                    
                    # Generate the perfect Excel file in memory
                    excel_data = sales_report.export_to_excel_perfect_streamlit(final_df)
                    
                    # Create a specific download button just for this mode
                    st.download_button(
                        label="📥 Download Perfectly Formatted Excel",
                        data=excel_data,
                        file_name="Zenxin_Sales_Report_Formatted.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
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
