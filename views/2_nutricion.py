import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import altair as alt
import numpy as np
from datetime import datetime
import pytz

# ==========================================
# 1. EXTRACT: Conexión Multi-Tabla (Data Warehouse)
# ==========================================
@st.cache_data(ttl=180) # Caché de 3 minutos para no saturar la API
def load_all_data():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(st.secrets["google_credentials"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet_id = "1oVmaWg-i4onBq9l8Nkql1mBXRUhAWO_kkH93Bda78tI"
    
    # Descargamos las 4 tablas necesarias para el Motor Dinámico
    doc = client.open_by_key(sheet_id)
    df_nut = pd.DataFrame(doc.worksheet("Nutricion").get_all_records())
    df_med = pd.DataFrame(doc.worksheet("Mediciones").get_all_records())
    df_met = pd.DataFrame(doc.worksheet("Metabolismo").get_all_records())
    df_train = pd.DataFrame(doc.worksheet("TESTbot").get_all_records())
    
    return df_nut, df_med, df_met, df_train

df_nut, df_med, df_met, df_train = load_all_data()

# ==========================================
# 2. TRANSFORM: ETL Y ALGORITMOS MATEMÁTICOS
# ==========================================
# --- HUSO HORARIO ---
tz_chile = pytz.timezone('America/Santiago')
hoy_dt = datetime.now(tz_chile)
hoy_str_corto = hoy_dt.strftime('%d/%m/%Y')
hoy_str_largo = hoy_dt.strftime('%Y-%m-%d')

dias_es = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
nombre_dia = dias_es[hoy_dt.weekday()]
fecha_formateada = f"{nombre_dia} {hoy_str_corto}"

# --- ETL NUTRICIÓN ---
# Limpieza de fechas y manejo Pitbull de nulos
df_nut['Fecha_Real'] = pd.to_datetime(df_nut['Fecha'], format='%d/%m/%Y %H:%M', errors='coerce')
df_nut['Solo_Fecha'] = df_nut['Fecha_Real'].dt.strftime('%d/%m/%Y')

# Convertimos macros a numéricos. Si hay errores (vacíos), forzamos a 0.
for col in ['Calorías', 'Proteínas', 'Grasas', 'Carbohidratos']:
    df_nut[col] = pd.to_numeric(df_nut[col], errors='coerce').fillna(0)

# Detección del Sabueso: Hay descripción pero Kcal es 0
df_nut['Encolado_Sabueso'] = (df_nut['Calorías'] == 0) & (df_nut['Descripción'] != "")

# Filtro de data de hoy
df_hoy = df_nut[df_nut['Solo_Fecha'] == hoy_str_corto]
macros_hoy = df_hoy[['Calorías', 'Proteínas', 'Grasas', 'Carbohidratos']].sum()

# --- ALGORITMO KATCH-MCARDLE (BMR REAL) ---
# Rescatamos la última medición válida
df_med['Fecha_Real'] = pd.to_datetime(df_med['Fecha'], dayfirst=True, errors='coerce')
df_med = df_med.sort_values('Fecha_Real').dropna(subset=['Peso (kg)', 'Cuello (cm)', 'Cintura (cm)'])

estatura_cm = 180.0
peso_kg = 102.0
cuello_cm = 42.0
cintura_cm = 108.0

if not df_med.empty:
    ultima_medicion = df_med.iloc[-1]
    peso_kg = float(ultima_medicion['Peso (kg)'])
    cuello_cm = float(ultima_medicion['Cuello (cm)'])
    cintura_cm = float(ultima_medicion['Cintura (cm)'])

# 1. Fórmula Marina de EE.UU. para Grasa Corporal
try:
    log_cintura_cuello = np.log10(cintura_cm - cuello_cm)
    log_estatura = np.log10(estatura_cm)
    body_fat_pct = (495.0 / (1.0324 - 0.19077 * log_cintura_cuello + 0.15456 * log_estatura)) - 450.0
except:
    body_fat_pct = 25.0 # Fallback de seguridad en caso de error matemático

# 2. Masa Magra y BMR
lean_body_mass = peso_kg * (1 - (body_fat_pct / 100.0))
bmr = 370 + (21.6 * lean_body_mass)

# --- FACTORES DINÁMICOS DE HOY ---
# ¿Entrena hoy? Buscamos en el excel de fuerza
df_train['Es_Hoy'] = df_train['Fecha'] == hoy_str_corto
entrena_hoy = not df_train[(df_train['Es_Hoy']) & (df_train['Ejercicio'] != '')].empty
bonus_entrenamiento = 400 if entrena_hoy else 0

# ¿Cuántos pasos lleva hoy?
df_met['Fecha_Real'] = pd.to_datetime(df_met['Fecha'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
df_met['Solo_Fecha'] = df_met['Fecha_Real'].dt.strftime('%d/%m/%Y')
pasos_hoy = df_met[df_met['Solo_Fecha'] == hoy_str_corto]['Pasos_Emma'].sum()
# Cálculo Conservador Factor Emma: 0.035 kcal por paso para cuerpos adaptados
bonus_pasos = pasos_hoy * 0.035 

# Gasto Total Dinámico (TDEE)
NEAT_BASE = 1.2 # Multiplicador de sedentarismo básico
tdee = (bmr * NEAT_BASE) + bonus_entrenamiento + bonus_pasos

# LÍMITES TERMODINÁMICOS
limite_deficit = tdee - 500
limite_mantenimiento = tdee
limite_hipertrofia = tdee + 300


# ==========================================
# 3. FRONT-END Y VISUALIZACIÓN
# ==========================================

st.title("🥩 Motor Termodinámico & Nutrición")

# --- BOTÓN DE RECARGA MANUAL Y RADAR SABUESO ---
col_head1, col_head2 = st.columns([0.8, 0.2])
with col_head2:
    if st.button("🔄 Forzar Lectura de Radar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

comidas_encoladas = df_hoy[df_hoy['Encolado_Sabueso'] == True]
if not comidas_encoladas.empty:
    st.warning(f"🐾 **SABUESO RASTREANDO:** Tienes {len(comidas_encoladas)} comida(s) de hoy encolada(s) procesándose por IA. Los datos en pantalla están parciales.")

# --- CONFIGURACIÓN DINÁMICA (ECONOMÍA) ---
with st.expander("⚙️ Configuración Dinámica de Macros (Presupuesto/Fase)", expanded=False):
    st.markdown("Ajusta tus multiplicadores según tu fase actual o presupuesto. Los Carbohidratos se recalcularán solos.")
    col_s1, col_s2 = st.columns(2)
    # Ajusta el 'value=1.8' al número exacto con el que quieres que inicie por defecto
    prot_multiplier = col_s1.slider("Proteína (g por kg de Masa Magra)", min_value=1.2, max_value=3.0, value=1.8, step=0.1)    
    # Ajusta el 'value=0.8' si necesitas cambiar la grasa base
    fat_multiplier = col_s2.slider("Grasa (g por kg de Peso Total)", min_value=0.5, max_value=1.5, value=0.8, step=0.1)

# Cálculo de Metas en base a los sliders
target_prot = lean_body_mass * prot_multiplier
target_fat = peso_kg * fat_multiplier
kcal_from_prot_fat = (target_prot * 4) + (target_fat * 9)
target_carbs = max(0, (limite_deficit - kcal_from_prot_fat) / 4) # Usamos límite de déficit como target base

st.markdown("---")

# --- VELOCÍMETRO TERMODINÁMICO ---
st.subheader("🔥 Balance Energético Dinámico (Hoy)")

kcal_consumidas = macros_hoy['Calorías']

# Lógica del Insight en vivo
if kcal_consumidas < limite_deficit:
    estado_color = "🔵 ZONA DE DÉFICIT"
    insight = f"Estás en déficit agresivo. Tienes margen de **{int(limite_deficit - kcal_consumidas)} Kcal** antes de llegar al límite de pérdida de grasa recomendada."
elif limite_deficit <= kcal_consumidas <= limite_mantenimiento:
    estado_color = "🟢 ZONA DE MANTENIMIENTO"
    insight = f"Has cruzado la línea. Tu cuerpo está estabilizado. Quedan **{int(limite_mantenimiento - kcal_consumidas)} Kcal** para empezar a ganar peso."
else:
    estado_color = "🔴 ZONA DE SUPERÁVIT / HIPERTROFIA"
    insight = "Estás construyendo masa (o almacenando grasa). Superaste el mantenimiento."

# Usamos la barra de progreso nativa de Streamlit hackeada como velocímetro
porcentaje_llenado = min((kcal_consumidas / limite_hipertrofia), 1.0) if limite_hipertrofia > 0 else 0

col1, col2 = st.columns([0.3, 0.7])
with col1:
    st.metric("Kcal Consumidas", f"{int(kcal_consumidas)}", delta=estado_color, delta_color="off")
with col2:
    st.progress(porcentaje_llenado)
    st.markdown(f"""
    **TDEE Calculado:** {int(tdee)} Kcal  *(BMR: {int(bmr)} | Pesas: +{bonus_entrenamiento} | Pasos: +{int(bonus_pasos)})*
    <br>💡 **Insight HD:** {insight}
    """, unsafe_allow_html=True)


st.markdown("---")

# --- PRINCIPIO DORIAN YATES (GRÁFICOS) ---
st.subheader("⚖️ Distribución de Combustible (Macros)")

col_donut, col_trend = st.columns(2)

with col_donut:
    st.markdown(f"##### 🍩 Fotografía del Día ({fecha_formateada})")
    # Armamos el DataFrame para el Donut
    df_macros_hoy = pd.DataFrame({
        'Macro': ['Proteínas', 'Grasas', 'Carbohidratos'],
        'Gramos': [macros_hoy['Proteínas'], macros_hoy['Grasas'], macros_hoy['Carbohidratos']],
        # Multiplicamos por sus kcal reales (P:4, G:9, C:4) para el porcentaje de energía
        'Kcal': [macros_hoy['Proteínas']*4, macros_hoy['Grasas']*9, macros_hoy['Carbohidratos']*4] 
    })
    
    if df_macros_hoy['Kcal'].sum() == 0:
        st.info("No hay comidas registradas con macros hoy.")
    else:
        # Gráfico de Anillo Altair
        donut = alt.Chart(df_macros_hoy).mark_arc(innerRadius=70).encode(
            theta=alt.Theta(field="Kcal", type="quantitative"),
            color=alt.Color(field="Macro", type="nominal", 
                            scale=alt.Scale(domain=['Proteínas', 'Grasas', 'Carbohidratos'],
                                            range=['#FF4B4B', '#FACA2B', '#00FFFF'])),
            tooltip=['Macro', 'Gramos', 'Kcal']
        ).properties(height=300)
        st.altair_chart(donut, use_container_width=True)

with col_trend:
    st.markdown("##### 📊 Cumplimiento de Metas (Gramos)")
    
    # Proteína
    st.write(f"**Proteína** ({macros_hoy['Proteínas']:.1f}g / {int(target_prot)}g target)")
    st.progress(min(macros_hoy['Proteínas'] / target_prot, 1.0) if target_prot > 0 else 0)
    
    # Grasa
    st.write(f"**Grasas** ({macros_hoy['Grasas']:.1f}g / {int(target_fat)}g target)")
    st.progress(min(macros_hoy['Grasas'] / target_fat, 1.0) if target_fat > 0 else 0)
    
    # Carbohidratos
    st.write(f"**Carbohidratos** ({macros_hoy['Carbohidratos']:.1f}g / {int(target_carbs)}g target)")
    st.progress(min(macros_hoy['Carbohidratos'] / target_carbs, 1.0) if target_carbs > 0 else 0)

st.markdown("---")

# ==========================================
# NUEVO BLOQUE: HISTORIAL TERMODINÁMICO
# ==========================================
st.subheader("📊 Historial Termodinámico (Últimos 7 días)")
st.markdown("*Evolución de tu ingesta calórica desglosada por macro-nutrientes. La línea punteada indica tu límite de Mantenimiento.*")

# Agrupamos por día y sumamos
df_hist = df_nut.groupby('Solo_Fecha').agg({
    'Proteínas': 'sum', 'Grasas': 'sum', 'Carbohidratos': 'sum', 'Calorías': 'sum', 'Fecha_Real': 'max'
}).reset_index()

# Filtramos días con datos, tomamos los últimos 7 y ordenamos cronológicamente de izquierda a derecha
df_hist = df_hist[df_hist['Calorías'] > 0].sort_values('Fecha_Real', ascending=False).head(7).sort_values('Fecha_Real', ascending=True)

if df_hist.empty:
    st.info("No hay datos históricos suficientes para graficar.")
else:
    # Transformación matemática a Kcal para escala real de energía
    df_hist['Kcal_Proteínas'] = df_hist['Proteínas'] * 4
    df_hist['Kcal_Grasas'] = df_hist['Grasas'] * 9
    df_hist['Kcal_Carbohidratos'] = df_hist['Carbohidratos'] * 4

    # Melt (Despivotar) para Altair
    df_melt = pd.melt(df_hist, id_vars=['Solo_Fecha', 'Calorías', 'Proteínas', 'Grasas', 'Carbohidratos'],
                      value_vars=['Kcal_Proteínas', 'Kcal_Grasas', 'Kcal_Carbohidratos'],
                      var_name='Macro', value_name='Kcal_Aportadas')

    # Limpieza visual de la leyenda
    df_melt['Macro'] = df_melt['Macro'].str.replace('Kcal_', '')

    # Construcción de la capa 1: Barras Apiladas (Ordinales)
    base_hist = alt.Chart(df_melt).encode(
        x=alt.X('Solo_Fecha:O', axis=alt.Axis(title='Día-Mes', labelAngle=-45), sort=None) 
    )

    bars_hist = base_hist.mark_bar(opacity=0.85).encode(
        y=alt.Y('Kcal_Aportadas:Q', title='Energía (Kcal)'),
        color=alt.Color('Macro:N', scale=alt.Scale(
            domain=['Proteínas', 'Grasas', 'Carbohidratos'],
            range=['#FF4B4B', '#FACA2B', '#00FFFF']
        )),
        order=alt.Order('Macro:N', sort='ascending'),
        tooltip=[
            alt.Tooltip('Solo_Fecha:N', title='Fecha'),
            alt.Tooltip('Calorías:Q', title='Kcal Totales del Día'),
            alt.Tooltip('Macro:N', title='Macro'),
            alt.Tooltip('Kcal_Aportadas:Q', title='Kcal Aportadas'),
            alt.Tooltip('Proteínas:Q', title='Total Proteína (g)'),
            alt.Tooltip('Grasas:Q', title='Total Grasa (g)'),
            alt.Tooltip('Carbohidratos:Q', title='Total Carbos (g)')
        ]
    )

    # Construcción de la capa 2: Línea de Mantenimiento TDEE
    df_target = pd.DataFrame({'Límite Mantenimiento': [tdee]})
    line_target = alt.Chart(df_target).mark_rule(color='white', strokeDash=[5, 5], size=2).encode(
        y='Límite Mantenimiento:Q',
        tooltip=[alt.Tooltip('Límite Mantenimiento:Q', title='TDEE actual (Mantenimiento)')]
    )

    # Renderizado final
    chart_hist = alt.layer(bars_hist, line_target).resolve_scale(y='shared').properties(height=350).interactive(bind_y=False)
    st.altair_chart(chart_hist, use_container_width=True)

st.markdown("---")


# --- AUDITORÍA DE PLATOS ---
with st.expander("📝 Registro Forense (Últimos Platos)", expanded=False):
    df_auditoria = df_nut.copy()
    # Filtramos los que sí tienen macros procesados
    df_auditoria = df_auditoria[df_auditoria['Calorías'] > 0]
    df_auditoria = df_auditoria.sort_values(by='Fecha_Real', ascending=False).head(15)
    
    # Columna 'Descripción' extirpada
    df_auditoria_clean = df_auditoria[['Fecha', 'Comida', 'Calorías', 'Proteínas', 'Grasas', 'Carbohidratos']]
    st.dataframe(df_auditoria_clean, hide_index=True, use_container_width=True)