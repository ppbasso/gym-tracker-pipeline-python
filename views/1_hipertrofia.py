import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import numpy as np
import re
import streamlit as st
import altair as alt
import json
import pytz 

# ==========================================
# 1. EXTRACT: Conexión a Google Sheets (Data Warehouse)
# ==========================================
@st.cache_data(ttl=300)
def load_data():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(st.secrets["google_credentials"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet_id = "1oVmaWg-i4onBq9l8Nkql1mBXRUhAWO_kkH93Bda78tI"
    doc = client.open_by_key(sheet_id)
    
    # Extraemos Entrenamiento y Mediciones Biométricas
    df_testbot = pd.DataFrame(doc.worksheet("TESTbot").get_all_records())
    df_med = pd.DataFrame(doc.worksheet("Mediciones").get_all_records())
    return df_testbot, df_med

# ==========================================
# 2. TRANSFORM: ETL y Auditoría Silenciosa
# ==========================================
def extract_real_weight(row):
    base_w_str = str(row['Peso Proyectado']).lower().replace('kg', '').strip()
    try: base_w = float(base_w_str)
    except: base_w = np.nan
        
    nota = str(row['Notas']).lower()
    for prefix in ['peso real:', 'peso real', 'sigo con', 'estoy con']:
        if prefix in nota:
            m = re.search(rf'{prefix}\s*(\d+\.?\d*)', nota)
            if m: return float(m.group(1))
            
    m_serie = re.search(r'serie.*?(\d+\.?\d*)\s*kg', nota)
    if m_serie: return float(m_serie.group(1))
    
    m_con = re.search(r'con\s*(\d+\.?\d*)\s*kg', nota)
    if m_con: return float(m_con.group(1))
    return base_w

def get_tier_biomecanico(ej):
    compuestos = [
        "Remo con Barra", "Press con Mancuernas Plano", "Press Inclinado con Mancuernas", 
        "Remo Inclinado con Mancuernas", "Remo a Una Mano con Mancuerna", 
        "Press de Hombro con Mancuernas Sentado", "Goblet Squat con Mancuerna", 
        "Peso Muerto Rumano con Mancuernas"
    ]
    return "Tier 1 (Compuesto)" if ej in compuestos else "Tier 2 (Aislamiento)"

def limpiar_flotante(val):
    if pd.isna(val) or str(val).strip() == "": return 0.0
    try: return float(str(val).replace(',', '.').strip())
    except: return 0.0

@st.cache_data(ttl=300)
def process_data(df):
    df = df[df['Ejercicio'] != ''].copy()
    
    # Normalización
    df['Ejercicio'] = df['Ejercicio'].str.replace(r'\s*\(\d+\)', '', regex=True).str.strip()
    ALIAS_MAP = {
        "Triceps Skull Crushers con Mancuernas": "Extension de Triceps con Mancuernas",
        "Extension de Triceps sobre cabeza": "Extension de Triceps con Mancuerna sobre cabeza",
        "Shrugs sentado con Mancuernas": "Shrugs (Encogimientos) Sentado"
    }
    df['Ejercicio'] = df['Ejercicio'].replace(ALIAS_MAP)
    
    df['Fecha'] = pd.to_datetime(df['Fecha'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['Fecha'])
    
    for c in ['S1', 'S2', 'S3']: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    df['Reps_Efectivas'] = np.where(df['S3'] > 0, df['S3'], np.where(df['S2'] > 0, df['S2'], df['S1']))
    
    df['Tiene_Descarga'] = df['Notas'].str.contains('descarga', case=False, na=False)
    fechas_descarga = df[df['Tiene_Descarga']]['Fecha'].unique()
    df['Es_Descarga'] = df['Fecha'].isin(fechas_descarga)
    df['Tipo_Sesion'] = np.where(df['Es_Descarga'], '🔄 Descarga', '⚡ Serie Efectiva')
    
    df['Peso_Proyectado_Num'] = df['Peso Proyectado'].astype(str).str.extract(r'(\d+\.?\d*)').astype(float)
    df['Peso_Real'] = df.apply(extract_real_weight, axis=1)
    df['Reps_Min_Meta'] = df['Sets x Reps'].astype(str).str.extract(r'x\s*(\d+)').astype(float).fillna(8)
    
    df['E1RM_Meta'] = df['Peso_Proyectado_Num'] / (1.0278 - (0.0278 * df['Reps_Min_Meta']))
    df['E1RM'] = np.where((df['Reps_Efectivas'] > 0), df['Peso_Real'] / (1.0278 - (0.0278 * df['Reps_Efectivas'])), np.nan)
    
    df['E1RM_Meta'] = df['E1RM_Meta'].round(2)
    df['E1RM'] = df['E1RM'].round(2)
    
    # Motor Lógico Silencioso: Clasificación Biomecánica
    df['Tier'] = df['Ejercicio'].apply(get_tier_biomecanico)
    
    # Traducción estricta a vocabulario clásico (sin inventos de "Tensión Máxima")
    df['Resultado'] = np.where(
        df['Es_Descarga'], '🔄 Descarga',
        np.where(
            df['Tier'] == 'Tier 1 (Compuesto)',
            np.where(df['E1RM'] > df['E1RM_Meta'] * 1.01, '🟢 Meta Superada',
            np.where(df['E1RM'] >= df['E1RM_Meta'] * 0.98, '🟡 Consolidado', '🔴 Fallo')),
            # En aislamiento, mantener el 90%+ de la fuerza meta es Consolidar (Límite biomecánico natural)
            np.where(df['E1RM'] > df['E1RM_Meta'] * 1.01, '🟢 Meta Superada',
            np.where(df['E1RM'] >= df['E1RM_Meta'] * 0.90, '🟡 Consolidado', '🔴 Fallo'))
        )
    )
    
    df = df.sort_values(by=['Ejercicio', 'Fecha'])
    
    hoy_dinamico = pd.Timestamp.now(tz='America/Santiago').normalize().tz_localize(None)
    dict_status = {}
    for ej in df['Ejercicio'].unique():
        df_ej = df[df['Ejercicio'] == ej]
        futuras = df_ej[df_ej['Fecha'] >= hoy_dinamico]['Fecha']
        prox_fecha = futuras.min() if not futuras.empty else pd.Timestamp('2099-12-31')
        dict_status[ej] = {
            'activo': prox_fecha != pd.Timestamp('2099-12-31'),
            'prox_fecha': prox_fecha
        }
        
    return df, dict_status

def get_grupo(ej):
    DICCIONARIO_BIOMECANICO = {
        "Press con Mancuernas Plano": "Pecho", "Press Inclinado con Mancuernas": "Pecho",
        "Remo con Barra": "Espalda", "Remo a Una Mano con Mancuerna": "Espalda", "Remo Inclinado con Mancuernas": "Espalda",
        "Press de Hombro con Mancuernas Sentado": "Hombros", "Shrugs (Encogimientos) Sentado": "Hombros", "Elevaciones Laterales con Mancuernas": "Hombros", "Pájaro (Vuelos Posteriores)": "Hombros",
        "Curl Biceps con Barra Recta": "Brazos", "Curl Bíceps Alterno con Mancuernas": "Brazos", "Zottman Curls": "Brazos", "Extension de Triceps con Mancuerna sobre cabeza": "Brazos", "Hammer Curl Biceps con Mancuernas Sentado": "Brazos", "Extension de Triceps con Mancuernas": "Brazos", "Curl Bicep Inclinado con Mancuernas": "Brazos", "Curl Bicep Concentrado": "Brazos",
        "Goblet Squat con Mancuerna": "Piernas", "Peso Muerto Rumano con Mancuernas": "Piernas"
    }
    return DICCIONARIO_BIOMECANICO.get(ej, "Otros")


# ==========================================
# 3. COMPONENTES VISUALES
# ==========================================
def render_chart_dual(df_ej_real):
    chart_data = df_ej_real.dropna(subset=['E1RM', 'E1RM_Meta']).copy()
    if chart_data.empty: return
    
    min_date = chart_data['Fecha'].min() - pd.Timedelta(days=2)
    max_date = chart_data['Fecha'].max() + pd.Timedelta(days=5)
    
    base = alt.Chart(chart_data).encode(
        x=alt.X('Fecha:T', axis=alt.Axis(format='%d-%m', title='Día-Mes', labelAngle=-45), scale=alt.Scale(domain=[min_date, max_date]))
    )
    
    line_meta = base.mark_line(color='#FFA500', size=4).encode(y=alt.Y('E1RM_Meta:Q', scale=alt.Scale(zero=False), title='Fuerza (kg)'))
    points_meta = base.mark_point(color='#FFA500', size=90, filled=True).encode(
        y='E1RM_Meta:Q', tooltip=[alt.Tooltip('Fecha:T', format='%d-%m-%Y', title='Fecha'), alt.Tooltip('E1RM_Meta:Q', title='🎯 Meta')]
    )
    
    line_real = base.mark_line(color='#00FFFF', size=4).encode(y='E1RM:Q')
    points_real = base.mark_point(color='#00FFFF', size=150, filled=True, opacity=0.9).encode(
        y='E1RM:Q', tooltip=[alt.Tooltip('Fecha:T', format='%d-%m-%Y', title='Fecha'), alt.Tooltip('Peso_Real:Q', title='Peso Real'), alt.Tooltip('E1RM:Q', title='⚡ E1RM')]
    )
    
    chart = alt.layer(line_meta, points_meta, line_real, points_real).resolve_scale(y='shared').properties(height=260).configure_view(strokeWidth=0).interactive(bind_y=False)
    st.altair_chart(chart, width="stretch")

def render_ejercicio_bloque(ej, df_g, is_activo=True): 
    df_ej = df_g[df_g['Ejercicio'] == ej].copy()
    df_ej_real = df_ej[df_ej['Reps_Efectivas'] > 0].copy()
    
    if df_ej_real.empty and is_activo:
        st.info("⏳ En fase de calibración: Esperando primera sesión.")
        return
    elif df_ej_real.empty:
        return
        
    ultimo = df_ej_real.iloc[-1]
    
    m1, m2 = st.columns(2)
    if ultimo['Es_Descarga']:
        e1rm_display, detalle_texto = "🔄 Descarga", "Semana de recuperación activa"
    else:
        e1rm_display = f"{ultimo['E1RM']} kg"
        detalle_texto = f"⚡ Real: {ultimo['Peso_Real']:g}kg x {int(ultimo['Reps_Efectivas'])} | 🎯 Meta: {ultimo['Peso_Proyectado_Num']:g}kg x {int(ultimo['Reps_Min_Meta'])}"
    
    m1.metric("Fuerza Actual (E1RM)", e1rm_display, delta=detalle_texto, delta_color="off")
    m2.metric("Auditoría Biomecánica", ultimo['Resultado'])
    
    render_chart_dual(df_ej_real)
    
    with st.expander("Ver Auditoría y Tabla Histórica"):
        df_disp = df_ej_real.copy()
        df_disp['Fecha_Str'] = df_disp['Fecha'].dt.strftime('%d-%m-%Y')
        df_disp['E1RM_Str'] = df_disp.apply(lambda row: "Descarga" if row['Es_Descarga'] else f"{row['E1RM']:.2f}", axis=1)
        df_disp = df_disp[['Fecha_Str', 'Peso_Proyectado_Num', 'Reps_Min_Meta', 'Peso_Real', 'Reps_Efectivas', 'E1RM_Meta', 'E1RM_Str', 'Resultado', 'Fecha']]
        df_disp.columns = ['Fecha', 'Peso Meta', 'Reps Meta', 'Peso Real', 'Reps Reales', 'E1RM Meta', 'E1RM Real', 'Auditoría', '_fecha_sort']
        df_disp = df_disp.sort_values(by='_fecha_sort', ascending=False).drop(columns=['_fecha_sort'])
        st.dataframe(df_disp, hide_index=True, width="stretch")
    st.markdown("<hr style='border:1px dashed #ccc'>", unsafe_allow_html=True)


# ==========================================
# 4. FRONT-END: UX PRINCIPAL Y MOTOR METABÓLICO
# ==========================================
df_raw, df_med_raw = load_data()
df_full, status_map = process_data(df_raw)
df_full['Grupo'] = df_full['Ejercicio'].apply(get_grupo)

st.title("🧠 Centro de Comando Heavy Duty")

df_real = df_full[df_full['Reps_Efectivas'] > 0]
if df_real.empty:
    st.warning("No hay datos ejecutados. Esperando registros.")
    st.stop()

# --- CÁLCULO DE MÉTRICAS GLOBALES ("13 de 15") ---
activos_nombres = [ej for ej, info in status_map.items() if info['activo']]
df_radar = df_real[df_real['Ejercicio'].isin(activos_nombres)]
ultimas_sesiones = df_radar[~df_radar['Es_Descarga']].sort_values('Fecha').groupby('Ejercicio').last()

total_auditados = len(ultimas_sesiones)
if total_auditados > 0:
    fallos = len(ultimas_sesiones[ultimas_sesiones['Resultado'] == '🔴 Fallo'])
    exitos = total_auditados - fallos
    tasa_exito = (exitos / total_auditados) * 100
    lista_exitos = ultimas_sesiones[ultimas_sesiones['Resultado'] != '🔴 Fallo'].index.tolist()
    lista_fallos = ultimas_sesiones[ultimas_sesiones['Resultado'] == '🔴 Fallo'].index.tolist()

# --- MOTOR DE DIAGNÓSTICO SILENCIOSO (Cruce de Datos sin UI de Tarjetas) ---
ultimas_sesiones_t1 = ultimas_sesiones[ultimas_sesiones['Tier'] == 'Tier 1 (Compuesto)']
total_t1 = len(ultimas_sesiones_t1)
tasa_exito_t1 = ((total_t1 - len(ultimas_sesiones_t1[ultimas_sesiones_t1['Resultado'] == '🔴 Fallo'])) / total_t1) * 100 if total_t1 > 0 else 100

df_med_raw['Peso_Clean'] = df_med_raw['Peso (kg)'].apply(limpiar_flotante)
df_med_raw['Cintura_Clean'] = df_med_raw['Cintura (cm)'].apply(limpiar_flotante)
df_med_raw['Fecha'] = pd.to_datetime(df_med_raw['Fecha'], dayfirst=True, errors='coerce')
df_med = df_med_raw.dropna(subset=['Fecha']).sort_values('Fecha')

pesos_validos = df_med[df_med['Peso_Clean'] > 0]['Peso_Clean'].tolist()
cinturas_validas = df_med[df_med['Cintura_Clean'] > 0]['Cintura_Clean'].tolist()

delta_peso = pesos_validos[-1] - pesos_validos[-2] if len(pesos_validos) >= 2 else 0
delta_cintura = cinturas_validas[-1] - cinturas_validas[-2] if len(cinturas_validas) >= 2 else 0

tendencia_fuerza = "Baja" if tasa_exito_t1 < 60 else "Alta/Estable"
tendencia_peso = "Sube" if delta_peso > 0.5 else ("Baja" if delta_peso < -0.5 else "Estable")
tendencia_cintura = "Sube" if delta_cintura > 0.5 else ("Baja" if delta_cintura < -0.5 else "Estable")

# Lógica del diagnóstico de campo
if tendencia_fuerza == "Alta/Estable" and tendencia_peso == "Baja" and tendencia_cintura == "Baja":
    consejo_accionable = "Recomposición perfecta. Quema de grasa con retención muscular confirmada por métricas. No toques nada."
    estado_snc, color_delta = "🟢 RECUPERACIÓN ÓPTIMA", "normal"
elif tendencia_fuerza == "Alta/Estable" and tendencia_peso != "Baja" and tendencia_cintura != "Baja":
    consejo_accionable = "Superávit oculto. Fuerza intacta pero la barriga no baja. Ve al panel de Nutrición y sube el 'Stock Crítico' al 20% para forzar déficit real."
    estado_snc, color_delta = "🟡 FALSO DÉFICIT", "off"
elif tendencia_fuerza == "Baja" and tendencia_peso == "Baja":
    consejo_accionable = "Catabolismo crítico. Fuerza cayendo en compuestos. Exige una recarga de carbohidratos (refeed) para proteger la masa magra hoy."
    estado_snc, color_delta = "🔴 SNC FATIGADO", "inverse"
elif tendencia_fuerza == "Baja" and tendencia_peso == "Sube":
    consejo_accionable = "Fuerza cae y peso sube (retención por cortisol/estrés sistémico). Reduce pesos al 50% en compuestos para vaciar fatiga acumulada."
    estado_snc, color_delta = "🔴 ALERTA CORTISOL", "inverse"
else:
    consejo_accionable = "Metabolismo estabilizando. Cumple las metas de la planilla y evalúa en el próximo pesaje dominical."
    estado_snc, color_delta = "🔵 FASE TRANSICIONAL", "off"

# --- CABECERA RESTAURADA (CUMPLIMIENTO DE METAS) ---
st.subheader(f"🎯 CUMPLIMIENTO DE METAS GLOBALES Y DIAGNÓSTICO")

if total_auditados > 0:
    col1, col2 = st.columns(2)
    col1.metric("Estado del Sistema Nervioso", estado_snc, delta=f"Tasa Global de Éxito: {tasa_exito:.0f}%", delta_color=color_delta)
    col2.metric(f"Ejercicios Superando Meta", f"{exitos} de {total_auditados}")
    
    st.info(f"💡 **Directriz HD:** {consejo_accionable}")

    with st.expander("Ver detalle general (Buscador Rápido de Fallos)"):
        c1, c2 = st.columns(2)
        c1.markdown("**🟢 Cumpliendo Meta:**\n" + ("\n".join([f"- {e}" for e in lista_exitos]) if lista_exitos else "Ninguno."))
        c2.markdown("**🔴 Fallando:**\n" + ("\n".join([f"- {e}" for e in lista_fallos]) if lista_fallos else "Ninguno."))

# --- EXTRACTOR FORENSE (NUEVA FASE 1) ---
st.markdown("---")
st.subheader("🕵️‍♂️ EXTRACTOR FORENSE (DATA WAREHOUSE)")
st.markdown("Descarga el historial completo de tus sesiones ejecutadas. Entrégale este archivo a tu IA para que analice tendencias, estancamientos y diseñe tu próximo macrociclo basándose en datos reales, no en resúmenes estáticos.")

# Construimos el DataFrame Maestro para la IA
# Seleccionamos y renombramos columnas para maximizar el entendimiento del LLM
df_maestro = df_real.copy()
df_maestro['Fecha'] = df_maestro['Fecha'].dt.strftime('%Y-%m-%d') # Formato universal ISO para IA

# Filtramos solo las columnas de valor analítico (limpiamos ruido)
columnas_clave = [
    'Fecha', 'Ejercicio', 'Grupo', 'Tier', 
    'Peso_Proyectado_Num', 'Reps_Min_Meta', 
    'Peso_Real', 'Reps_Efectivas', 
    'E1RM_Meta', 'E1RM', 
    'Resultado', 'Notas'
]
df_maestro = df_maestro[columnas_clave]

# Renombramos para que la IA no tenga que adivinar el significado de las variables
df_maestro.columns = [
    'Fecha', 'Ejercicio', 'Grupo_Muscular', 'Tier_Biomecanico',
    'Peso_Meta_kg', 'Reps_Meta',
    'Peso_Real_kg', 'Reps_Reales',
    'E1RM_Proyectado', 'E1RM_Real',
    'Auditoria_Semaforo', 'Notas_Originales'
]

# Convertimos a formato CSV con BOM (utf-8-sig) y separador ';' para compatibilidad nativa con Excel en español
csv_data = df_maestro.to_csv(index=False, sep=';').encode('utf-8-sig')

# Desplegamos el botón nativo de descarga
st.download_button(
    label="📥 Descargar CSV Maestro (Q2-2026)",
    data=csv_data,
    file_name="Auditoria_Historica_Q2_2026.csv",
    mime="text/csv",
    use_container_width=True
)

st.markdown("---")

# --- MOTOR DE VISTA DUAL (BIOMECÁNICA VS OPERATIVA) ---
modo_vista = st.radio(
    "🔄 Selecciona el Eje de Análisis:",
    ["🔬 Por Grupo Muscular (Biomecánica)", "⚙️ Por Módulos de Entrenamiento (Operativa)"],
    horizontal=True
)

if modo_vista == "🔬 Por Grupo Muscular (Biomecánica)":
    st.markdown("### 🔬 AUDITORÍA POR GRUPO MUSCULAR")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🚀 Pecho", "🦇 Espalda", "🥥 Hombros", "🦵 Piernas", "🦾 Brazos"])

    def render_musculo(nombre_grupo):
        df_g = df_full[df_full['Grupo'] == nombre_grupo]
        if df_g.empty: return
            
        ejercicios = df_g['Ejercicio'].unique()
        activos_info, inactivos_list = [], []
        
        for ej in ejercicios:
            if status_map[ej]['activo']:
                activos_info.append({'nombre': ej, 'prox_fecha': status_map[ej]['prox_fecha']})
            else:
                inactivos_list.append(ej)
                
        activos_info.sort(key=lambda x: x['prox_fecha'])
        vivos_ordenados = [x['nombre'] for x in activos_info]
        
        if vivos_ordenados:
            st.markdown("#### 🟢 RUTINA ACTIVA")
            for ej in vivos_ordenados:
                prox_f = status_map[ej]['prox_fecha']
                etiqueta_dia = f"[{prox_f.strftime('%d/%m')}]" if prox_f.year != 2099 else "[Activo]"
                st.markdown(f"##### {etiqueta_dia} {ej}")
                render_ejercicio_bloque(ej, df_g, is_activo=True)
                
        if inactivos_list:
            with st.expander("⚫ HISTÓRICO / INACTIVOS (Cementerio)"):
                for ej in inactivos_list:
                    st.markdown(f"##### {ej} (Inactivo)")
                    render_ejercicio_bloque(ej, df_g, is_activo=False)

    with tab1: render_musculo("Pecho")
    with tab2: render_musculo("Espalda")
    with tab3: render_musculo("Hombros")
    with tab4: render_musculo("Piernas")
    with tab5: render_musculo("Brazos")

else:
    st.markdown("### ⚙️ AUDITORÍA POR MÓDULOS DE ENTRENAMIENTO")
    tabA, tabB = st.tabs(["🐺 Módulo Alpha", "Ω Módulo Omega"])
    
    MODULO_ALPHA = [
        "Press con Mancuernas Plano", "Remo Inclinado con Mancuernas", "Press Inclinado con Mancuernas",
        "Pájaro (Vuelos Posteriores)", "Elevaciones Laterales con Mancuernas", "Curl Bicep Concentrado",
        "Extension de Triceps con Mancuernas", "Shrugs (Encogimientos) Sentado", "Goblet Squat con Mancuerna"
    ]
    
    MODULO_OMEGA = [
        "Remo con Barra", "Press con Mancuernas Plano", "Press de Hombro con Mancuernas Sentado",
        "Remo a Una Mano con Mancuerna", "Curl Bíceps Alterno con Mancuernas", 
        "Extension de Triceps con Mancuerna sobre cabeza", "Zottman Curls", "Goblet Squat con Mancuerna"
    ]
    
    def render_modulo(lista_ejercicios):
        for ej in lista_ejercicios:
            if ej in status_map:
                df_g = df_full[df_full['Ejercicio'] == ej]
                is_activo = status_map[ej]['activo']
                prox_f = status_map[ej]['prox_fecha']
                etiqueta_dia = f"[{prox_f.strftime('%d/%m')}]" if prox_f.year != 2099 else "[Activo]"
                estado = "🟢" if is_activo else "⚫ (Inactivo)"
                st.markdown(f"##### {estado} {etiqueta_dia} {ej}")
                render_ejercicio_bloque(ej, df_g, is_activo=is_activo)
            else:
                st.markdown(f"##### ⏳ {ej}")
                st.info("Sin registros históricos aún en Google Sheets para este ejercicio.")

    with tabA: render_modulo(MODULO_ALPHA)
    with tabB: render_modulo(MODULO_OMEGA)

    st.markdown("---")
    with st.expander("⚫ HISTÓRICO / INACTIVOS (Cementerio)", expanded=False):
        st.markdown("Ejercicios que ya no están programados en el Excel a futuro, pero mantienen su registro de fuerza.")
        ejercicios_activos_ahora = MODULO_ALPHA + MODULO_OMEGA
        todos_los_ejercicios_bd = df_full['Ejercicio'].unique()
        ejercicios_inactivos = [ej for ej in todos_los_ejercicios_bd if ej not in ejercicios_activos_ahora]
        
        if ejercicios_inactivos:
            for ej in ejercicios_inactivos:
                st.markdown(f"##### 🪦 {ej} (Inactivo)")
                render_ejercicio_bloque(ej, df_full[df_full['Ejercicio'] == ej], is_activo=False)
        else:
            st.success("No hay ejercicios inactivos en el sistema.")