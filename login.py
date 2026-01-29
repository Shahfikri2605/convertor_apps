import streamlit as st
import streamlit_authenticator as stauth
from app import main_app_interface, get_gspread_client, make_url

st.set_page_config(page_title="Zenxin Data Extractor", page_icon="🤖")
@st.cache_data(ttl=600)
def get_users_from_sheet(url):
    try:
        client = get_gspread_client()
        sh = client.open_by_url(url)
        ws = sh.worksheet("Users")
        records = ws.get_all_records()

        credentials = {"usernames": {}}
        permissions = {}
        for row in records:
            username = str(row['username'])
            credentials["usernames"][username] = {
                "name": row['name'],
                "password": str(row['password'])
            }
            # Handle empty permission cells gracefully
            sys_str = str(row.get('systems', 'ALL'))
            if not sys_str.strip(): sys_str = "ALL"
            
            store_str = str(row.get('stores', 'ALL'))
            if not store_str.strip(): store_str = "ALL"
            
            permissions[username] = {
                "systems": [s.strip() for s in sys_str.split(',') if s.strip()],
                "stores": [s.strip() for s in store_str.split(',') if s.strip()]
            }
        return credentials, permissions
    except Exception as e:
        st.error(f"Error loading users: {e}")
        return None, None

# 1. Load Secrets
try:
    USERS_SHEET_URL = make_url(st.secrets["sheet_ids"]["users_db"])
except:
    st.error("Missing 'users_db' in secrets.toml")
    st.stop()

# 2. Authenticate
credentials, permissions = get_users_from_sheet(USERS_SHEET_URL)

if credentials:
    authenticator = stauth.Authenticate(
        credentials,
        st.secrets["auth"]["cookie_name"],
        st.secrets["auth"]["cookie_key"],
        st.secrets["auth"]["expiry_days"]
    )
    
    # Render Login
    authenticator.login(location='main')

    if st.session_state["authentication_status"] is False:
        st.error('Username/password is incorrect')
    elif st.session_state["authentication_status"] is None:
        st.warning('Please enter your username and password')
    elif st.session_state["authentication_status"] is True:
        # Load Permissions
        user = st.session_state["username"]
        user_perms = permissions.get(user, {"systems": ["ALL"], "stores": ["ALL"]})
        
        # 3. Launch Main App

        main_app_interface(authenticator, st.session_state["name"], user_perms)

