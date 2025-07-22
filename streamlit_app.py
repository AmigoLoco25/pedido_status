import streamlit as st
import requests
import pandas as pd
import io
import ast

# ------------------- AUTHENTICATION -------------------
password = st.text_input("Enter password", type="password")
if password != st.secrets["app_password"]:
    st.stop()

# ------------------- CONFIG -------------------
st.title("📦 Pedido Status via /shippeditems")
API_KEY = st.secrets["api_key"]
HEADERS = {"accept": "application/json", "key": API_KEY}

pedido_docnum = st.text_input("Enter Pedido docNumber (e.g., Wix250212):")
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()

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

def extract_products_from_pedido(row):
    items = row.get("products", [])
    if isinstance(items, str):
        items = ast.literal_eval(items)
    return pd.DataFrame([
        {
            "SKU": item.get("sku"),
            "Product Name": item.get("name"),
            "Units Ordered": item.get("units")
        }
        for item in items if item.get("sku")
    ])

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
        albaran_row = albaranes_df[albaranes_df["pedido_id"] == pedido_id].head(1)
        albaran_docnum = albaran_row["Albaran DocNum"].values[0] if not albaran_row.empty else "N/A"

        st.markdown(f"**Pedido**: `{pedido_docnum}` → **Albarán**: `{albaran_docnum}`")

        # --- Get original pedido product lines ---
        pedido_df = extract_products_from_pedido(pedido_row)
        if pedido_df.empty:
            st.warning("No valid products found in Pedido.")
            st.stop()

        # --- Get shipped items from Holded API ---
        shipped_df = get_shipped_items(pedido_id)
        shipped_df.rename(columns={
            "sku": "SKU",
            "name": "Product Name",
            "sent": "Units Sent",
            "pending": "Units Pending"
        }, inplace=True)

        # Ensure all necessary columns exist
        for col in ["SKU", "Product Name", "Units Sent", "Units Pending"]:
            if col not in shipped_df.columns:
                shipped_df[col] = 0

        # --- Merge ---
        merged_df = pedido_df.merge(
            shipped_df[["SKU", "Product Name", "Units Sent", "Units Pending"]],
            on=["SKU", "Product Name"],
            how="left"
        )

        merged_df["Units Sent"] = merged_df["Units Sent"].fillna(0).astype(int)
        merged_df["Units Pending"] = merged_df["Units Pending"].fillna(0).astype(int)
        merged_df["Units Ordered"] = merged_df["Units Ordered"].astype(int)

        merged_df["Status"] = merged_df["Units Pending"].apply(
            lambda x: (
                f"Enviado (Extra {abs(x)})" if x < 0
                else "Enviado" if x == 0
                else f"Pendiente (Falta {x})"
            )
        )

        merged_df["Units Shipped"] = (
            merged_df["Units Sent"].astype(str) + "/" + merged_df["Units Ordered"].astype(str)
        )

        final_df = merged_df[["SKU", "Product Name", "Units Ordered", "Units Shipped", "Units Pending", "Status"]]

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
