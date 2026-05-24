import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import altair as alt
from datetime import datetime
import pytz

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

# ⚠️ CORRECCIÓN CLÍNICA: Aislar "Ayer" de "Hoy"
df_historico = df_diario[df_diario['Solo_Fecha'] != hoy_str_corto].copy()
df_historico['Media_7d'] = df_historico['Pasos_Emma'].rolling(window=7, min_periods=1).mean()

pasos_hoy_serie = df_diario[df_diario['Solo_Fecha'] == hoy_str_corto]['Pasos_Emma']
pasos_hoy = pasos_hoy_serie.sum() if not pasos_hoy_serie.empty else 0

# --- ALGORITMO DE BALANCEO SNC ---
df_train['Es_Hoy'] = df_train['Fecha'] == hoy_str_corto
entrena_hoy = not df_train[(df_train['Es_Hoy']) & (df_train['Ejercicio'] != '')].empty

# Definición dinámica de metas
if entrena_hoy:
    meta_pasos = 8000
    insight_meta = "El SNC está bajo ataque. Target de recuperación."
else:
    meta_pasos = 13000
    insight_meta = "No hay estrés mecánico hoy. Forzando quema calórica."

# Cálculos de Diferencia y Factor Emma (Solo si evaluáramos un día cerrado, hoy es info en curso)
diferencia = pasos_hoy - meta_pasos
factor_emma = 0

if diferencia >= 0:
    if diferencia > 0:
        factor_emma = diferencia

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

# --- TARJETA DE COMANDO (HOY) ---
st.subheader("Estado Actual (Día en Curso)")

c1, c2, c3 = st.columns(3)

# La métrica de pasos hoy no te castiga en rojo, solo informa.
c1.metric("Pasos Registrados Hoy", f"{int(pasos_hoy):,}".replace(",", "."), delta="Esperando cierre a las 23:00", delta_color="off")
c2.metric("Target de Hoy", f"{int(meta_pasos):,}".replace(",", "."), delta=insight_meta, delta_color="off")
c3.metric("Status de Operación", "En Progreso ⏳", delta="Iphone en reposo", delta_color="off")

st.markdown("---")

# --- EL MOTOR NEAT (GRÁFICO TENDENCIAL HISTÓRICO) ---
st.subheader("📊 Radar de Gasto Energético (Evaluación Histórica)")
st.markdown("*Este gráfico evalúa tu rendimiento consolidado hasta el día de ayer, ignorando los vacíos del día en curso.*")

# Filtramos los últimos 30 días del histórico (excluye hoy)
df_30d = df_historico.tail(30).copy()

if df_30d.empty:
    st.info("No hay datos suficientes para graficar el radar.")
else:
    # Gráfico Base - ⚠️ CORRECCIÓN DE BUG: 'Solo_Fecha:O' (Ordinal)
    base = alt.Chart(df_30d).encode(
        x=alt.X('Solo_Fecha:O', axis=alt.Axis(title='Día-Mes', labelAngle=-45))
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