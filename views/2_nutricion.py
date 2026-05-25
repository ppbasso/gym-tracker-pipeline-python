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

def limpiar_flotante(val):
    if pd.isna(val) or str(val).strip() == "": 
        return 0.0
    try: 
        return float(str(val).replace(',', '.').strip())
    except: 
        return 0.0

tz_chile = pytz.timezone('America/Santiago')
hoy_dt = datetime.now(tz_chile)
hoy_str_corto = hoy_dt.strftime('%d/%m/%Y')
hoy_str_largo = hoy_dt.strftime('%Y-%m-%d')

dias_es = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
nombre_dia = dias_es[hoy_dt.weekday()]
fecha_formateada = f"{nombre_dia} {hoy_str_corto}"

# --- ETL NUTRICIÓN ---
df_nut['Fecha_Real'] = pd.to_datetime(df_nut['Fecha'], format='%d/%m/%Y %H:%M', errors='coerce')
df_nut['Solo_Fecha'] = df_nut['Fecha_Real'].dt.strftime('%d/%m/%Y')

for col in ['Calorías', 'Proteínas', 'Grasas', 'Carbohidratos']:
    if col in df_nut.columns:
        df_nut[col] = df_nut[col].apply(limpiar_flotante)

df_nut['Encolado_Sabueso'] = (df_nut['Calorías'] == 0) & (df_nut['Descripción'] != "")

# Extracción Atómica y Blindada (A prueba de KeyError)
df_hoy = df_nut[df_nut['Solo_Fecha'] == hoy_str_corto]
kcal_consumidas = df_hoy['Calorías'].sum() if not df_hoy.empty and 'Calorías' in df_hoy.columns else 0.0
prot_consumidas = df_hoy['Proteínas'].sum() if not df_hoy.empty and 'Proteínas' in df_hoy.columns else 0.0
gras_consumidas = df_hoy['Grasas'].sum() if not df_hoy.empty and 'Grasas' in df_hoy.columns else 0.0
carb_consumidas = df_hoy['Carbohidratos'].sum() if not df_hoy.empty and 'Carbohidratos' in df_hoy.columns else 0.0

# --- ALGORITMO KATCH-MCARDLE ---
df_med['Fecha_Real'] = pd.to_datetime(df_med['Fecha'], dayfirst=True, errors='coerce')
df_med = df_med.sort_values('Fecha_Real').dropna(subset=['Peso (kg)', 'Cuello (cm)', 'Cintura (cm)'])

estatura_cm = 180.0
peso_kg = 102.0
cuello_cm = 42.0
cintura_cm = 108.0

if not df_med.empty:
    ultima_medicion = df_med.iloc[-1]
    peso_kg = limpiar_flotante(ultima_medicion['Peso (kg)'])
    cuello_cm = limpiar_flotante(ultima_medicion['Cuello (cm)'])
    cintura_cm = limpiar_flotante(ultima_medicion['Cintura (cm)'])

try:
    log_cintura_cuello = np.log10(cintura_cm - cuello_cm)
    log_estatura = np.log10(estatura_cm)
    body_fat_pct = (495.0 / (1.0324 - 0.19077 * log_cintura_cuello + 0.15456 * log_estatura)) - 450.0
except:
    body_fat_pct = 25.0 

lean_body_mass = peso_kg * (1 - (body_fat_pct / 100.0))
bmr = 370 + (21.6 * lean_body_mass)

# --- FACTORES DINÁMICOS DE HOY ---
df_train['Es_Hoy'] = df_train['Fecha'] == hoy_str_corto
entrena_hoy = not df_train[(df_train['Es_Hoy']) & (df_train['Ejercicio'] != '')].empty
bonus_entrenamiento = 400 if entrena_hoy else 0

df_met['Fecha_Real'] = pd.to_datetime(df_met['Fecha'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
df_met['Solo_Fecha'] = df_met['Fecha_Real'].dt.strftime('%d/%m/%Y')
if 'Pasos_Emma' in df_met.columns:
    df_met['Pasos_Emma'] = df_met['Pasos_Emma'].apply(limpiar_flotante)
    pasos_hoy = df_met[df_met['Solo_Fecha'] == hoy_str_corto]['Pasos_Emma'].sum()
else:
    pasos_hoy = 0.0

bonus_pasos = pasos_hoy * 0.035 
NEAT_BASE = 1.2 
tdee = (bmr * NEAT_BASE) + bonus_entrenamiento + bonus_pasos

limite_deficit = tdee - 500
limite_mantenimiento = tdee
limite_hipertrofia = tdee + 300

# ==========================================
# 3. FRONT-END Y VISUALIZACIÓN
# ==========================================
st.title("🥩 Motor Termodinámico & Nutrición")

col_head1, col_head2 = st.columns([0.8, 0.2])
with col_head2:
    if st.button("🔄 Forzar Lectura", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

comidas_encoladas = df_hoy[df_hoy['Encolado_Sabueso'] == True]
if not comidas_encoladas.empty:
    st.warning(f"🐾 **SABUESO RASTREANDO:** Tienes {len(comidas_encoladas)} comida(s) procesándose por IA. Datos parciales.")

with st.expander("⚙️ Configuración Dinámica de Macros", expanded=False):
    col_s1, col_s2 = st.columns(2)
    prot_multiplier = col_s1.slider("Proteína (g por kg Magra)", min_value=1.2, max_value=3.0, value=1.8, step=0.1)    
    fat_multiplier = col_s2.slider("Grasa (g por kg Peso Total)", min_value=0.5, max_value=1.5, value=0.8, step=0.1)

target_prot = lean_body_mass * prot_multiplier
target_fat = peso_kg * fat_multiplier
kcal_from_prot_fat = (target_prot * 4) + (target_fat * 9)
target_carbs = max(0, (limite_deficit - kcal_from_prot_fat) / 4) 

st.markdown("---")
st.subheader("🔥 Balance Energético Dinámico (Hoy)")

if kcal_consumidas < limite_deficit:
    estado_color = "🔵 ZONA DE DÉFICIT"
    insight = f"Estás en déficit agresivo. Margen de **{int(limite_deficit - kcal_consumidas)} Kcal** antes de límite recomendado."
elif limite_deficit <= kcal_consumidas <= limite_mantenimiento:
    estado_color = "🟢 ZONA DE MANTENIMIENTO"
    insight = f"Cuerpo estabilizado. Quedan **{int(limite_mantenimiento - kcal_consumidas)} Kcal** para ganar peso."
else:
    estado_color = "🔴 ZONA DE SUPERÁVIT"
    insight = "Estás construyendo masa o almacenando grasa. Superaste el mantenimiento."

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
st.subheader("⚖️ Distribución de Combustible")

col_donut, col_trend = st.columns(2)

with col_donut:
    st.markdown(f"##### 🍩 Fotografía del Día ({fecha_formateada})")
    df_macros_hoy = pd.DataFrame({
        'Macro': ['Proteínas', 'Grasas', 'Carbohidratos'],
        'Gramos': [prot_consumidas, gras_consumidas, carb_consumidas],
        'Kcal': [prot_consumidas*4, gras_consumidas*9, carb_consumidas*4] 
    })
    
    if df_macros_hoy['Kcal'].sum() == 0:
        st.info("No hay comidas registradas con macros hoy.")
    else:
        donut = alt.Chart(df_macros_hoy).mark_arc(innerRadius=70).encode(
            theta=alt.Theta(field="Kcal", type="quantitative"),
            color=alt.Color(field="Macro", type="nominal", 
                            scale=alt.Scale(domain=['Proteínas', 'Grasas', 'Carbohidratos'],
                                            range=['#FF4B4B', '#FACA2B', '#00FFFF'])),
            tooltip=['Macro', 'Gramos', 'Kcal']
        ).properties(height=300)
        st.altair_chart(donut, use_container_width=True)

with col_trend:
    st.markdown("##### 📊 Cumplimiento de Metas")
    
    st.write(f"**Proteína** ({prot_consumidas:.1f}g / {int(target_prot)}g target)")
    st.progress(min(prot_consumidas / target_prot, 1.0) if target_prot > 0 else 0)
    
    # --- CORRECCIÓN INTEGRADA: 'target_fat' en vez de 'target_grupo' ---
    st.write(f"**Grasas** ({gras_consumidas:.1f}g / {int(target_fat)}g target)")
    st.progress(min(gras_consumidas / target_fat, 1.0) if target_fat > 0 else 0)
    
    st.write(f"**Carbohidratos** ({carb_consumidas:.1f}g / {int(target_carbs)}g target)")
    st.progress(min(carb_consumidas / target_carbs, 1.0) if target_carbs > 0 else 0)

st.markdown("---")
st.subheader("📊 Historial Termodinámico (Últimos 7 días)")

df_hist = df_nut.groupby('Solo_Fecha').agg({
    'Proteínas': 'sum', 'Grasas': 'sum', 'Carbohidratos': 'sum', 'Calorías': 'sum', 'Fecha_Real': 'max'
}).reset_index()

df_hist = df_hist[df_hist['Calorías'] > 0].sort_values('Fecha_Real', ascending=False).head(7).sort_values('Fecha_Real', ascending=True)

if df_hist.empty:
    st.info("No hay datos históricos suficientes.")
else:
    df_hist['Kcal_Proteínas'] = df_hist['Proteínas'] * 4
    df_hist['Kcal_Grasas'] = df_hist['Grasas'] * 9
    df_hist['Kcal_Carbohidratos'] = df_hist['Carbohidratos'] * 4

    df_melt = pd.melt(df_hist, id_vars=['Solo_Fecha', 'Calorías'],
                      value_vars=['Kcal_Proteínas', 'Kcal_Grasas', 'Kcal_Carbohidratos'],
                      var_name='Macro', value_name='Kcal_Aportadas')

    df_melt['Macro'] = df_melt['Macro'].str.replace('Kcal_', '')

    base_hist = alt.Chart(df_melt).encode(x=alt.X('Solo_Fecha:O', axis=alt.Axis(title='Día-Mes', labelAngle=-45), sort=None))
    
    bars_hist = base_hist.mark_bar(opacity=0.85).encode(
        y=alt.Y('Kcal_Aportadas:Q', title='Energía (Kcal)'),
        color=alt.Color('Macro:N', scale=alt.Scale(domain=['Proteínas', 'Grasas', 'Carbohidratos'], range=['#FF4B4B', '#FACA2B', '#00FFFF'])),
        order=alt.Order('Macro:N', sort='ascending'),
        tooltip=[alt.Tooltip('Solo_Fecha:N', title='Fecha'), alt.Tooltip('Macro:N', title='Macro'), alt.Tooltip('Kcal_Aportadas:Q', title='Kcal')]
    )

    df_target = pd.DataFrame({'Límite Mantenimiento': [tdee]})
    line_target = alt.Chart(df_target).mark_rule(color='white', strokeDash=[5, 5], size=2).encode(
        y='Límite Mantenimiento:Q', tooltip=[alt.Tooltip('Límite Mantenimiento:Q', title='TDEE actual')]
    )

    chart_hist = alt.layer(bars_hist, line_target).resolve_scale(y='shared').properties(height=350).interactive(bind_y=False)
    st.altair_chart(chart_hist, use_container_width=True)

st.markdown("---")
with st.expander("📝 Registro Forense (Últimos Platos)", expanded=False):
    df_auditoria = df_nut[df_nut['Calorías'] > 0].sort_values(by='Fecha_Real', ascending=False).head(15)
    if not df_auditoria.empty:
        st.dataframe(df_auditoria[['Fecha', 'Descripción', 'Calorías', 'Proteínas', 'Grasas', 'Carbohidratos']], hide_index=True, use_container_width=True)
    else:
        st.info("No hay platos procesados recientes.")