import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import altair as alt
from datetime import datetime
import pytz

# ==========================================
# CONFIGURACIÓN DE PÁGINA Y HACK CSS (TOC)
# ==========================================
st.set_page_config(page_title="Regulador Metabólico", page_icon="🔋", layout="wide")

# HACK CSS: Capitaliza el menú lateral sin alterar los nombres de archivo en minúsculas
st.markdown("""
    <style>
        [data-testid="stSidebarNav"] ul li a span {
            text-transform: capitalize;
            font-size: 1.1rem;
            letter-spacing: 0.5px;
        }
    </style>
""", unsafe_allow_html=True)

# --- SEGURIDAD Y LOGIN ---
if "autenticado" not in st.session_state or not st.session_state["autenticado"]:
    st.warning("⚠️ Acceso denegado. Por favor, identifícate en la página principal (dashboard).")
    st.stop()

# ==========================================
# 1. EXTRACT: Conexión a Data Warehouse
# ==========================================
@st.cache_data(ttl=180)
def load_metabolic_data():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(st.secrets["google_credentials"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet_id = "1oVmaWg-i4onBq9l8Nkql1mBXRUhAWO_kkH93Bda78tI"
    
    doc = client.open_by_key(sheet_id)
    df_met = pd.DataFrame(doc.worksheet("Metabolismo").get_all_records())
    df_train = pd.DataFrame(doc.worksheet("TESTbot").get_all_records())
    
    return df_met, df_train

df_met, df_train = load_metabolic_data()

# ==========================================
# 2. TRANSFORM: ETL Y ALGORITMO METABÓLICO
# ==========================================
tz_chile = pytz.timezone('America/Santiago')
hoy_dt = datetime.now(tz_chile)
hoy_str_corto = hoy_dt.strftime('%d/%m/%Y')

# --- ETL METABOLISMO (Pasos) ---
df_met['Fecha_Real'] = pd.to_datetime(df_met['Fecha'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
df_met = df_met.dropna(subset=['Fecha_Real'])
df_met['Solo_Fecha'] = df_met['Fecha_Real'].dt.strftime('%d/%m/%Y')
df_met['Pasos_Emma'] = pd.to_numeric(df_met['Pasos_Emma'], errors='coerce').fillna(0)

# Agrupamos por día para tener el total diario
df_diario = df_met.groupby('Solo_Fecha').agg({'Pasos_Emma': 'sum', 'Fecha_Real': 'max'}).reset_index()
df_diario = df_diario.sort_values('Fecha_Real')

# Calculamos la Media Móvil de 7 días (Rolling Average)
df_diario['Media_7d'] = df_diario['Pasos_Emma'].rolling(window=7, min_periods=1).mean()

pasos_hoy = df_diario[df_diario['Solo_Fecha'] == hoy_str_corto]['Pasos_Emma'].sum()

# --- ALGORITMO DE BALANCEO SNC ---
df_train['Es_Hoy'] = df_train['Fecha'] == hoy_str_corto
entrena_hoy = not df_train[(df_train['Es_Hoy']) & (df_train['Ejercicio'] != '')].empty

# Definición dinámica de metas
if entrena_hoy:
    meta_pasos = 8000
    modo_actual = "🛡️ Recuperación Activa (Día de Pesas)"
    insight_meta = "El SNC está bajo ataque. Meta reducida para priorizar reparación muscular."
else:
    meta_pasos = 13000
    modo_actual = "🔥 NEAT Agresivo (Día de Descanso)"
    insight_meta = "No hay estrés mecánico hoy. Meta elevada para forzar la quema calórica periférica."

# Cálculos de Diferencia y Factor Emma
diferencia = pasos_hoy - meta_pasos
factor_emma = 0

if diferencia >= 0:
    estado_meta = "🟢 Meta Cumplida"
    if diferencia > 0:
        factor_emma = diferencia
else:
    estado_meta = "🔴 En Progreso"

# ==========================================
# 3. FRONT-END Y VISUALIZACIÓN
# ==========================================
st.title("🔋 Regulador Metabólico & NEAT")

col_head1, col_head2 = st.columns([0.8, 0.2])
with col_head2:
    if st.button("🔄 Forzar Sincronización", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.markdown("---")

# --- TARJETA DE COMANDO METABÓLICO ---
st.subheader(f"Estado Actual: {modo_actual}")
st.markdown(f"*{insight_meta}*")

c1, c2, c3 = st.columns(3)

# Métrica 1: Pasos Reales
c1.metric("Pasos de Hoy", f"{int(pasos_hoy):,}".replace(",", "."), delta=estado_meta, delta_color="normal" if diferencia >= 0 else "off")

# Métrica 2: La Meta Dinámica
c2.metric("Límite Estratégico", f"{int(meta_pasos):,}".replace(",", "."), delta="Target Algorítmico", delta_color="off")

# Métrica 3: Factor Emma (Excedente)
if factor_emma > 0:
    c3.metric("🐾 Factor Emma (Bonus)", f"+{int(factor_emma):,}".replace(",", "."), delta="Eficiencia Calórica", delta_color="normal")
else:
    c3.metric("🐾 Factor Emma (Bonus)", "0", delta="Esperando paseos extra", delta_color="off")

# Barra de progreso del día
progreso = min((pasos_hoy / meta_pasos), 1.0) if meta_pasos > 0 else 0
st.progress(progreso)

st.markdown("---")

# --- EL MOTOR NEAT (GRÁFICO TENDENCIAL) ---
st.subheader("📊 Radar de Gasto Energético (Últimos 30 Días)")

# Filtramos los últimos 30 días
df_30d = df_diario.tail(30).copy()

if df_30d.empty:
    st.info("No hay datos suficientes para graficar el radar.")
else:
    # Gráfico Base
    base = alt.Chart(df_30d).encode(
        x=alt.X('Fecha_Real:T', axis=alt.Axis(format='%d-%m', title='Día-Mes', labelAngle=-45))
    )
    
    # Barras de pasos diarios
    barras = base.mark_bar(color='#4A90E2', opacity=0.7).encode(
        y=alt.Y('Pasos_Emma:Q', title='Volumen de Pasos'),
        tooltip=[alt.Tooltip('Solo_Fecha:N', title='Fecha'), 
                 alt.Tooltip('Pasos_Emma:Q', title='Pasos Reales')]
    )
    
    # Línea de Media Móvil (La verdadera tendencia metabólica)
    linea_tendencia = base.mark_line(color='#FF4B4B', size=4).encode(
        y=alt.Y('Media_7d:Q'),
        tooltip=[alt.Tooltip('Solo_Fecha:N', title='Fecha'), 
                 alt.Tooltip('Media_7d:Q', title='Promedio 7 Días')]
    )
    
    # Puntos de la media móvil para mejor hit-box del tooltip
    puntos_tendencia = base.mark_point(color='#FF4B4B', size=50, filled=True).encode(
        y=alt.Y('Media_7d:Q')
    )
    
    # Unificamos capas
    grafico_mixto = alt.layer(barras, linea_tendencia, puntos_tendencia).resolve_scale(
        y='shared'
    ).properties(height=350).interactive(bind_y=False)
    
    st.altair_chart(grafico_mixto, use_container_width=True)
    
    st.markdown("""
        <div style='text-align: center; font-size: 0.9rem; color: #aaa;'>
            <span style='color:#4A90E2;'>■</span> <b>Barras Azules:</b> Impacto diario (Ruido) | 
            <span style='color:#FF4B4B;'>■</span> <b>Línea Roja:</b> Media Móvil de 7 días (Tendencia Real del Metabolismo)
        </div>
    """, unsafe_allow_html=True)