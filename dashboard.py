import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import numpy as np
import re
import streamlit as st
import altair as alt
import json

# ==========================================
# CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(page_title="Centro Comando HD", page_icon="💪", layout="wide")

# --- SEGURIDAD Y LOGIN ---
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

if not st.session_state["autenticado"]:
    st.markdown("<h2 style='text-align: center;'>🔒 Acceso Restringido</h2>", unsafe_allow_html=True)
    pwd = st.text_input("Ingresa la clave de comando:", type="password")
    if pwd == st.secrets["PASSWORD_MAESTRA"]:
        st.session_state["autenticado"] = True
        st.rerun()
    elif pwd:
        st.error("Contraseña incorrecta. El SNC te vigila.")
    st.stop() # Detiene la ejecución del resto del código si no hay login
# -------------------------

# ==========================================
# 1. EXTRACT: Conexión a Google Sheets (Vía Secrets)
# ==========================================
@st.cache_data(ttl=300)
def load_data():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    
    cred_dict = {
        "type": st.secrets["type"],
        "project_id": st.secrets["project_id"],
        "private_key_id": st.secrets["private_key_id"],
        "private_key": st.secrets["private_key"],
        "client_email": st.secrets["client_email"],
        "client_id": st.secrets["client_id"],
        "auth_uri": st.secrets["auth_uri"],
        "token_uri": st.secrets["token_uri"],
        "auth_provider_x509_cert_url": st.secrets["auth_provider_x509_cert_url"],
        "client_x509_cert_url": st.secrets["client_x509_cert_url"]
    }
    
    creds = Credentials.from_service_account_info(cred_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key("1oVmaWg-i4onBq9l8Nkql1mBXRUhAWO_kkH93Bda78tI").worksheet("TESTbot")
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    
    # ------------------------------------------
    # ETL (Transformación Forense)
    # ------------------------------------------
    df.columns = df.columns.str.strip()
    df['Fecha'] = pd.to_datetime(df['Fecha'], format='%d/%m/%Y', errors='coerce')
    
    # Limpiamos el texto del peso proyectado
    df['Meta_Peso_Num'] = df['Meta_Peso'].astype(str).str.lower().str.replace('kg', '').str.strip()
    df['Meta_Peso_Num'] = pd.to_numeric(df['Meta_Peso_Num'], errors='coerce').fillna(0)

    # El corazón del sistema: La Regex Extractor
    def extract_real_weight(row):
        nota = str(row['Nota_Fuerza']).lower()
        base_w = row['Meta_Peso_Num']
        
        # Patrón 1: "Peso real: X"
        for prefix in ['peso real:', 'peso real', 'sigo con', 'estoy con']:
            if prefix in nota:
                m = re.search(rf'{prefix}\s*(\d+\.?\d*)', nota)
                if m: return float(m.group(1))
        
        # Patrón 2: "serie... X kg"
        m_serie = re.search(r'serie.*?(\d+\.?\d*)\s*kg', nota)
        if m_serie: return float(m_serie.group(1))

        # Patrón 3: "con X kg"
        m_con = re.search(r'con\s*(\d+\.?\d*)\s*kg', nota)
        if m_con: return float(m_con.group(1))

        return base_w

    df['Peso_Levantado'] = df.apply(extract_real_weight, axis=1)
    
    # Limpieza de Repeticiones y Filtro de Basura
    df['Repeticiones_Reales'] = pd.to_numeric(df['Reps'], errors='coerce')
    df_clean = df.dropna(subset=['Repeticiones_Reales']).copy()
    
    # E1RM = Peso * (1 + 0.0333 * Reps)
    df_clean['E1RM'] = df_clean['Peso_Levantado'] * (1 + 0.0333 * df_clean['Repeticiones_Reales'])
    df_clean['E1RM'] = df_clean['E1RM'].round(1)

    # Identificación Biomecánica (Corregida con los nuevos ejercicios del Q2)
    def get_grupo(ejercicio):
        ej = ejercicio.lower()
        if any(x in ej for x in ["pecho", "press con mancuernas plano", "press inclinado"]): return "Pecho"
        if any(x in ej for x in ["remo", "espalda"]): return "Espalda"
        if any(x in ej for x in ["curl", "triceps", "zottman"]): return "Brazos"
        if any(x in ej for x in ["press de hombro", "pájaro", "elevaciones", "vuelos", "shrugs", "encogimientos"]): return "Hombros"
        if any(x in ej for x in ["squat", "peso muerto", "pierna", "rumano"]): return "Piernas"
        return "Core/Otros"

    df_clean['Grupo_Muscular'] = df_clean['Ejercicio'].apply(get_grupo)
    return df, df_clean

df_full, df_clean = load_data()

# ==========================================
# 2. MOTOR DE RENDERIZADO VISUAL
# ==========================================

# CSS Táctico (Heavy Duty Vibe)
st.markdown("""
    <style>
    .main {background-color: #0e1117;}
    h1, h2, h3 {color: #ff4b4b; font-family: 'Arial Black', sans-serif; text-transform: uppercase;}
    .metric-box {
        background-color: #1a1c24; border-left: 5px solid #ff4b4b;
        padding: 15px; border-radius: 5px; margin-bottom: 10px;
    }
    .metric-title {color: #a0a0a0; font-size: 0.9em; margin-bottom: 5px;}
    .metric-value {color: #ffffff; font-size: 1.8em; font-weight: bold;}
    .status-ok {color: #00ff00; font-weight: bold;}
    .status-warn {color: #ffaa00; font-weight: bold;}
    .status-alert {color: #ff0000; font-weight: bold;}
    </style>
""", unsafe_allow_html=True)

st.title("🛰️ Centro de Comando: Heavy Duty V2.0")

# --- NAVEGACIÓN ---
tabs = st.tabs(["📊 Macro-Visión", "🦾 Tracker de Fuerza (E1RM)", "📋 Auditoría por Módulos"])

# ------------------------------------------
# TAB 1: MACRO-VISIÓN (El Radar)
# ------------------------------------------
with tabs[0]:
    st.markdown("### 📡 Radar de Sobrecarga Progresiva")
    
    col1, col2, col3, col4 = st.columns(4)
    
    total_sesiones = df_clean['Fecha'].nunique()
    tonelaje_total = (df_clean['Peso_Levantado'] * df_clean['Repeticiones_Reales']).sum()
    
    # Delta de Fuerza (Últimos 14 días vs Anteriores)
    dos_semanas_atras = df_clean['Fecha'].max() - pd.Timedelta(days=14)
    df_reciente = df_clean[df_clean['Fecha'] >= dos_semanas_atras]
    df_anterior = df_clean[df_clean['Fecha'] < dos_semanas_atras]
    
    delta_e1rm = 0
    if not df_reciente.empty and not df_anterior.empty:
        delta_e1rm = df_reciente['E1RM'].mean() - df_anterior['E1RM'].mean()

    with col1:
        st.markdown(f"<div class='metric-box'><div class='metric-title'>Total Sesiones Completadas</div><div class='metric-value'>{total_sesiones}</div></div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div class='metric-box'><div class='metric-title'>Tonelaje Total Movido</div><div class='metric-value'>{tonelaje_total:,.0f} kg</div></div>", unsafe_allow_html=True)
    with col3:
        color = "status-ok" if delta_e1rm > 0 else "status-warn"
        signo = "+" if delta_e1rm > 0 else ""
        st.markdown(f"<div class='metric-box'><div class='metric-title'>Delta Fuerza (14d)</div><div class='metric-value {color}'>{signo}{delta_e1rm:.1f} kg</div></div>", unsafe_allow_html=True)
    with col4:
        st.markdown(f"<div class='metric-box'><div class='metric-title'>Último Entreno</div><div class='metric-value'>{df_clean['Fecha'].max().strftime('%d/%m/%Y')}</div></div>", unsafe_allow_html=True)

    # Gráfico de Distribución del Tonelaje
    st.markdown("---")
    tonelaje_por_grupo = df_clean.groupby('Grupo_Muscular').apply(lambda x: (x['Peso_Levantado'] * x['Repeticiones_Reales']).sum()).reset_index(name='Tonelaje')
    
    fig_pie = alt.Chart(tonelaje_por_grupo).mark_arc(innerRadius=50).encode(
        theta=alt.Theta(field="Tonelaje", type="quantitative"),
        color=alt.Color(field="Grupo_Muscular", type="nominal", scale=alt.Scale(scheme="reds")),
        tooltip=['Grupo_Muscular', alt.Tooltip('Tonelaje:Q', format=',.0f')]
    ).properties(title="Distribución del Esfuerzo (Tonelaje por Grupo)", height=300)
    
    st.altair_chart(fig_pie, use_container_width=True)

# ------------------------------------------
# TAB 2: TRACKER DE FUERZA (La Curva de Verdad)
# ------------------------------------------
with tabs[1]:
    st.markdown("### 📈 Curva del 1RM Estimado")
    
    filtro_grupo = st.selectbox("🎯 Enfocar en Grupo Muscular:", ["Todos"] + list(df_clean['Grupo_Muscular'].unique()))
    
    df_plot = df_clean if filtro_grupo == "Todos" else df_clean[df_clean['Grupo_Muscular'] == filtro_grupo]
    
    lista_ejs = sorted(df_plot['Ejercicio'].unique())
    filtro_ej = st.selectbox("🏋️‍♂️ Seleccionar Ejercicio Específico:", ["Todos"] + lista_ejs)
    
    if filtro_ej != "Todos":
        df_plot = df_plot[df_plot['Ejercicio'] == filtro_ej]

    if not df_plot.empty:
        fig_line = alt.Chart(df_plot).mark_line(point=True, strokeWidth=3).encode(
            x=alt.X('Fecha:T', title='Fecha de Sesión'),
            y=alt.Y('E1RM:Q', title='1RM Estimado (kg)', scale=alt.Scale(zero=False)),
            color=alt.Color('Ejercicio:N', scale=alt.Scale(scheme='set1')),
            tooltip=[alt.Tooltip('Fecha:T', format='%d/%m/%Y'), 'Ejercicio', 'Peso_Levantado', 'Repeticiones_Reales', 'E1RM']
        ).properties(height=400)
        
        st.altair_chart(fig_line, use_container_width=True)
    else:
        st.warning("No hay datos de fuerza registrados para este filtro.")

# ------------------------------------------
# TAB 3: AUDITORÍA POR MÓDULOS (El Organizador de Batalla)
# ------------------------------------------
with tabs[2]:
    st.markdown("### 📋 Análisis de Rutinas Estáticas")
    
    # Motor de Detección de Estado
    def get_status_ejercicios(df_total):
        status_dict = {}
        hoy = pd.Timestamp.now()
        for ej in df_total['Ejercicio'].unique():
            df_ej = df_total[df_total['Ejercicio'] == ej]
            
            fechas_futuras = df_ej[df_ej['Fecha'] >= hoy]['Fecha']
            is_activo = not fechas_futuras.empty
            
            # Buscar próxima fecha programada
            if is_activo:
                prox_fecha = fechas_futuras.min()
            else:
                prox_fecha = pd.Timestamp('2099-12-31') 
                
            status_dict[ej] = {
                'activo': is_activo,
                'prox_fecha': prox_fecha
            }
        return status_dict

    status_map = get_status_ejercicios(df_full)

    # -----------------------------------------------------
    # MATRICES DE LOS MÓDULOS (Actualizados para Q2 - 11/05)
    # -----------------------------------------------------
    MODULO_ALPHA = [
        "Press con Mancuernas Plano",
        "Remo Inclinado con Mancuernas",
        "Press Inclinado con Mancuernas",
        "Pájaro (Vuelos Posteriores)",
        "Elevaciones Laterales con Mancuernas",
        "Curl Bicep Concentrado",
        "Extension de Triceps con Mancuernas",
        "Shrugs (Encogimientos) Sentado",
        "Goblet Squat con Mancuerna"
    ]
    
    MODULO_OMEGA = [
        "Remo con Barra",
        "Press con Mancuernas Plano",
        "Press de Hombro con Mancuernas Sentado",
        "Remo a Una Mano con Mancuerna",
        "Curl Bíceps Alterno con Mancuernas",
        "Extension de Triceps sobre cabeza", 
        "Zottman Curls",
        "Goblet Squat con Mancuerna"
    ]
    
    def render_ejercicio_bloque(ejercicio_nombre, dataframe):
        """Renderiza la pastilla de historial debajo de cada ejercicio."""
        df_ej = dataframe.dropna(subset=['Repeticiones_Reales']).sort_values(by='Fecha', ascending=False)
        if df_ej.empty:
            st.info("Sin registros históricos válidos.")
            return

        cols = st.columns(4)
        for i in range(min(4, len(df_ej))):
            row = df_ej.iloc[i]
            fecha_str = row['Fecha'].strftime('%d/%m')
            
            with cols[i]:
                st.markdown(f"""
                <div style="background-color: #262730; padding: 10px; border-radius: 5px; font-size: 0.85em;">
                    <div style="color: #ff4b4b; font-weight: bold; margin-bottom: 5px;">📅 {fecha_str}</div>
                    <b>Reps:</b> {row['Repeticiones_Reales']} <br>
                    <b>Peso Real:</b> {row['Peso_Levantado']}kg <br>
                    <b>1RM:</b> {row['E1RM']}kg
                </div>
                """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
    
    def render_modulo(lista_ejercicios):
        for ej in lista_ejercicios:
            if ej in status_map:
                df_g = df_full[df_full['Ejercicio'] == ej]
                is_activo = status_map[ej]['activo']
                prox_f = status_map[ej]['prox_fecha']
                etiqueta_dia = f"[{prox_f.strftime('%d/%m')}]" if prox_f.year != 2099 else "[Activo]"
                estado = "🟢" if is_activo else "⚫ (Inactivo)"
                
                st.markdown(f"##### {estado} {etiqueta_dia} {ej}")
                render_ejercicio_bloque(ej, df_g)
            else:
                st.markdown(f"##### ⚪ [Esperando Datos] {ej}")
                st.info("Este ejercicio está en la matriz, pero aún no tiene datos registrados en el Excel.")

    colA, colB = st.columns(2)
    with colA:
        st.markdown("### 🐺 RUTINA ALPHA (Lunes)")
        render_modulo(MODULO_ALPHA)
        
    with colB:
        st.markdown("### Ω RUTINA OMEGA (Viernes)")
        render_modulo(MODULO_OMEGA)

    # ------------------------------------------
    # EL CEMENTERIO DE HISTÓRICOS (Para ejercicios reemplazados)
    # ------------------------------------------
    st.markdown("---")
    with st.expander("⚫ HISTÓRICO / INACTIVOS (Cementerio)", expanded=False):
        st.markdown("Ejercicios que ya no están programados en el Excel a futuro, pero mantienen su registro de fuerza.")
        
        ejercicios_activos_ahora = MODULO_ALPHA + MODULO_OMEGA
        todos_los_ejercicios_bd = df_full['Ejercicio'].unique()
        
        ejercicios_inactivos = [ej for ej in todos_los_ejercicios_bd if ej not in ejercicios_activos_ahora]
        
        if ejercicios_inactivos:
            for ej in ejercicios_inactivos:
                st.markdown(f"##### 🪦 {ej}")
                render_ejercicio_bloque(ej, df_full[df_full['Ejercicio'] == ej])
        else:
            st.success("No hay ejercicios inactivos en el sistema.")