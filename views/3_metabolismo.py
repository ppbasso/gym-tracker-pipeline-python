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
    # INYECCIÓN: Extracción de la tabla de biometría para cruzarla con el metabolismo
    df_med = pd.DataFrame(doc.worksheet("Mediciones").get_all_records())
    
    return df_met, df_train, df_med

df_met, df_train, df_med = load_metabolic_data()

# ==========================================
# 2. TRANSFORM: ETL Y ALGORITMO METABÓLICO
# ==========================================
def limpiar_flotante(val):
    """Higieniza strings de gsheets con comas/puntos para forzar float nativo."""
    if pd.isna(val) or str(val).strip() == "": 
        return 0.0
    try: 
        return float(str(val).replace(',', '.').strip())
    except: 
        return 0.0

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


# --- NUEVO MOTOR: RASTREADOR BIOMÉTRICO CON MEDIA MÓVIL ---
if not df_med.empty:
    # 1. Parseo forense de fechas y limpieza antibalística de peso
    df_med['Fecha_Real'] = pd.to_datetime(df_med['Fecha'], dayfirst=True, errors='coerce')
    df_med = df_med.dropna(subset=['Fecha_Real'])
    df_med['Solo_Fecha'] = df_med['Fecha_Real'].dt.strftime('%d/%m/%Y')
    df_med['Peso_Clean'] = df_med['Peso (kg)'].apply(limpiar_flotante)
    
    # 2. Filtrar solo filas con peso válido y agrupar por día (toma el último peso del día si hay duplicados)
    df_peso = df_med[df_med['Peso_Clean'] > 0]
    df_peso_diario = df_peso.groupby('Solo_Fecha').agg({
        'Peso_Clean': 'last',
        'Fecha_Real': 'max'
    }).reset_index().sort_values('Fecha_Real')
    
    # 3. Cálculo de la Verdad Absoluta: Media Móvil de 7 períodos
    df_peso_diario['Media_7d_Peso'] = df_peso_diario['Peso_Clean'].rolling(window=7, min_periods=1).mean()
else:
    df_peso_diario = pd.DataFrame()


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
    st.info("No hay datos suficientes para graficar el radar de NEAT.")
else:
    # Gráfico Base - ⚠️ CORRECCIÓN DE BUG: 'Solo_Fecha:O' (Ordinal)
    base = alt.Chart(df_30d).encode(
        x=alt.X('Solo_Fecha:O', axis=alt.Axis(title='Día-Mes', labelAngle=-45), sort=None)
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

st.markdown("---")

# --- NUEVO BLOQUE: RASTREADOR BIOMÉTRICO DE PÉRDIDA DE GRASA ---
st.subheader("📉 Rastreador Biométrico (Pérdida de Grasa Real)")
st.markdown("*Los puntos azules muestran tu peso diario (ruido por agua, sodio, estrés). La **línea roja gruesa** es tu Media Móvil de 7 días: esta es tu verdadera composición corporal.*")

if df_peso_diario.empty:
    st.info("No hay registros de peso suficientes para trazar la Media Móvil.")
else:
    # Filtramos los últimos 30 días de pesajes para no colapsar la pantalla
    df_peso_30d = df_peso_diario.tail(30).copy()
    
    # Ajuste del eje Y para que no arranque desde cero y el gráfico se vea detallado (efecto zoom)
    min_peso = df_peso_30d['Peso_Clean'].min() - 2
    max_peso = df_peso_30d['Peso_Clean'].max() + 2
    
    base_peso = alt.Chart(df_peso_30d).encode(
        x=alt.X('Solo_Fecha:O', axis=alt.Axis(title='Día-Mes', labelAngle=-45), sort=None)
    )
    
    # Capa 1: El Ruido Diario (Puntos de dispersión)
    puntos_peso = base_peso.mark_circle(color='#4A90E2', size=80, opacity=0.5).encode(
        y=alt.Y('Peso_Clean:Q', scale=alt.Scale(domain=[min_peso, max_peso]), title='Peso Diario (kg)'),
        tooltip=[
            alt.Tooltip('Solo_Fecha:N', title='Fecha Registro'), 
            alt.Tooltip('Peso_Clean:Q', title='Peso en Báscula (Ruido)')
        ]
    )
    
    # Capa 2: La Verdad Matemática (Línea de Media Móvil 7d)
    linea_peso_ma = base_peso.mark_line(color='#FF4B4B', size=4).encode(
        y=alt.Y('Media_7d_Peso:Q'),
        tooltip=[
            alt.Tooltip('Solo_Fecha:N', title='Fecha Cálculo'), 
            alt.Tooltip('Media_7d_Peso:Q', title='Media Móvil 7d (Pérdida Real)', format='.2f')
        ]
    )
    
    # Renderizado Multicapa
    grafico_peso = alt.layer(puntos_peso, linea_peso_ma).resolve_scale(y='shared').properties(height=350).interactive(bind_y=False)
    st.altair_chart(grafico_peso, use_container_width=True)