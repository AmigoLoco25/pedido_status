import streamlit as st
import requests
import pandas as pd
import io

# ------------------- AUTHENTICATION -------------------
password = st.text_input("Enter password", type="password")
if password != st.secrets["app_password"]:
    st.stop()

# ------------------- CONFIG -------------------
st.title("📦 Pedido Status")
API_KEY = st.secrets["api_key"]
HEADERS = {"accept": "application/json", "key": API_KEY}

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()

pedido_docnum = st.text_input("Enter Pedido docNumber (e.g., SO250070):")

@st.cache_data(ttl=3600)
def fetch_pedidos():
    url = "https://api.holded.com/api/invoicing/v1/documents/salesorder"
    response = requests.get(url, headers=HEADERS)
    return pd.DataFrame(response.json())

@st.cache_data(ttl=3600)
def fetch_albaranes():
    url = "https://api.holded.com/api/invoicing/v1/documents/waybill"
    response = requests.get(url, headers=HEADERS)
    df = pd.DataFrame(response.json())
    df["fromID"] = df["from"].apply(lambda d: d.get("id") if isinstance(d, dict) else None)
    return df.rename(columns={"docNumber": "Albaran DocNum", "id": "Albaran id", "fromID": "pedido_id"})

def get_row_by_docnumber(df, docnum):
    matches = df[df["docNumber"].str.lower() == docnum.lower()]
    return matches.iloc[0] if not matches.empty else None

def get_shipped_items(pedido_id):
    url = f"https://api.holded.com/api/invoicing/v1/documents/salesorder/{pedido_id}/shippeditems"
    resp = requests.get(url, headers=HEADERS)
    return pd.DataFrame(resp.json())

# ------------------- MAIN APP -------------------
if pedido_docnum:
    pedidos_df = fetch_pedidos()
    albaranes_df = fetch_albaranes()

    pedido_row = get_row_by_docnumber(pedidos_df, pedido_docnum)

    if pedido_row is not None:
        pedido_id = pedido_row["id"]
        albaran_rows = albaranes_df[albaranes_df["pedido_id"] == pedido_id]
        if not albaran_rows.empty:
            albaran_docnums = albaran_rows["Albaran DocNum"].tolist()
            albaran_display = ", ".join(f"`{docnum}`" for docnum in albaran_docnums)
        else:
            albaran_display = "N/A"

        st.markdown(f"**Pedido**: `{pedido_docnum}` → **Albarán**: `{albaran_display}`")

        # --- Get product data from shippeditems ---
        shipped_df = get_shipped_items(pedido_id)
        shipped_df.rename(columns={
            "sku": "SKU",
            "name": "Product Name",
            "sent": "Units Sent",
            "total": "Units Ordered"
        }, inplace=True)

        if shipped_df.empty:
            st.warning("No product data found in shippeditems.")
            st.stop()

        # Normalize and calculate fields
        shipped_df["SKU"] = shipped_df["SKU"].astype(str)
        shipped_df["Units Ordered"] = shipped_df["Units Ordered"].astype(int)
        shipped_df["Units Sent"] = shipped_df["Units Sent"].astype(int)

        shipped_df["Units Shipped"] = (
            shipped_df["Units Sent"].astype(str) + "/" + shipped_df["Units Ordered"].astype(str)
        )

        shipped_df["Status"] = (shipped_df["Units Sent"] - shipped_df["Units Ordered"]).apply(
            lambda x: (
                f"Enviado (Extra {abs(x)})" if x > 0
                else "Enviado" if x == 0
                else f"Pendiente (Falta {abs(x)})"
            )
        )

        final_df = shipped_df[["SKU", "Product Name", "Units Ordered", "Units Shipped", "Status"]]

        def highlight_status(row):
            color = ''
            if "Enviado" in row['Status']:
                color = 'background-color: #d4edda;'  # light green
            elif "Pendiente" in row['Status']:
                color = 'background-color: #f8d7da;'  # light red
            return ['' for _ in row[:-1]] + [color]

        st.subheader("📊 Product Shipping Status")
        st.dataframe(final_df.style.apply(highlight_status, axis=1))

        # --- Download Excel ---
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            final_df.to_excel(writer, index=False, sheet_name='Status')
        excel_buffer.seek(0)

        st.download_button(
            label="📥 Download Excel",
            data=excel_buffer,
            file_name=f"{pedido_docnum}_status.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    else:
        st.warning("Pedido docNumber not found.")
