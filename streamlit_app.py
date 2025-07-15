import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone
import pytz
import ast

# ------------------- AUTHENTICATION -------------------
password = st.text_input("Enter password", type="password")

if password != st.secrets["app_password"]:
    st.stop()
    
# Title
st.title("📦 Pedido Status")
API_KEY = st.secrets["api_key"]
HEADERS = {"accept": "application/json", "key": API_KEY}
# Input
pedido_docnum = st.text_input("Enter Pedido docNumber (e.g., Wix250212):")

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()

# API Call functions
@st.cache_data(ttl=3600)
def fetch_data():
    API_KEY = st.secrets["api_key"]
    headers = {"accept": "application/json", "key": API_KEY}

    pedidos = requests.get(
        "https://api.holded.com/api/invoicing/v1/documents/salesorder", headers=headers).json()
    albaranes = requests.get(
        "https://api.holded.com/api/invoicing/v1/documents/waybill", headers=headers).json()

    pedidos_df = pd.DataFrame(pedidos)
    albaran_df = pd.DataFrame(albaranes)

    # Clean and join the data
    albaran_df['fromID'] = albaran_df['from'].apply(lambda d: d.get('id') if isinstance(d, dict) else None)
    albaran_df.rename(columns={"docNumber": "Albaran DocNum", "id": "Albaran id", "fromID": "id"}, inplace=True)

    main_df = pedidos_df[['id', "docNumber"]]
    main_df = pd.merge(main_df, albaran_df[['id', 'Albaran DocNum', "Albaran id"]], on='id', how='left')
    main_df.rename(columns={"id": "Pedido id"}, inplace=True)

    return pedidos_df, albaran_df, main_df

# Helper functions
def get_row_index_by_docnumber(df, doc_number):
    matches = df.index[df['docNumber'] == doc_number]
    return int(matches[0]) if not matches.empty else None

def extract_skus_from_row(df, index):
    try:
        row = df.loc[index]
        product_list = row['products']
        if isinstance(product_list, str):
            product_list = ast.literal_eval(product_list)

        return pd.DataFrame([
            {'SKU': item['sku'], 'Product Name': item['name'], 'Units': item['units']}
            for item in product_list
        ])
    except Exception as e:
        st.error(f"Error extracting SKUs: {e}")
        return pd.DataFrame()

# Main logic
if pedido_docnum:
    pedidos_df, albaran_df, main_df = fetch_data()

    index = get_row_index_by_docnumber(main_df, pedido_docnum)

    if index is not None:
        albaran_docnum = main_df.loc[index, "Albaran DocNum"]
        st.markdown(f"**Pedido**: `{pedido_docnum}` → **Albarán**: `{albaran_docnum}`")

        pedido_index = get_row_index_by_docnumber(pedidos_df, pedido_docnum)
        pedido_df = extract_skus_from_row(pedidos_df, pedido_index)

        if pd.notna(albaran_docnum):
            albaran_df_temp = albaran_df.rename(columns={"Albaran DocNum": "docNumber"}).copy()
            albaran_index = get_row_index_by_docnumber(albaran_df_temp, albaran_docnum)
            albaran_product_df = extract_skus_from_row(albaran_df_temp, albaran_index)
        else:
            albaran_product_df = pd.DataFrame(columns=['SKU', 'Product Name', 'Units'])

        merged_df = pedido_df.merge(
            albaran_product_df, on=['SKU', 'Product Name'], how='left', suffixes=('', '_df2'))
        merged_df['Units_df2'] = merged_df['Units_df2'].fillna(0).astype(int)
        merged_df['Units Missing'] = merged_df['Units'] - merged_df['Units_df2']
        merged_df['Status'] = merged_df['Units Missing'].apply(
            lambda x: (
                f"Enviado (Extra {abs(x)})" if x < 0
                else "Enviado" if x == 0
                else f"Pendiente (Falta {x})"
            )
        )        
        merged_df['Units_df2'] = merged_df['Units_df2'].astype(str) + '/' + merged_df['Units'].astype(str)
        merged_df.drop(columns=['Units Missing'], inplace=True)
        merged_df.rename(columns={"Units": "Units Ordered", "Units_df2": "Units Shipped"}, inplace=True)


        def highlight_status(row):
            color = ''
            if "Enviado" in row['Status']:
                color = 'background-color: #d4edda;'  # light green
            elif "Pendiente" in row['Status']:
                color = 'background-color: #f8d7da;'  # light red
            return ['' for _ in row[:-1]] + [color]  # apply color only to last column
        
        st.subheader("📊 Product Shipping Status")
        st.dataframe(merged_df.style.apply(highlight_status, axis=1))

        csv = merged_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 Download CSV", csv, "order_status.csv", "text/csv")
    else:
        st.warning("Pedido docNumber not found. Please check your input.")
