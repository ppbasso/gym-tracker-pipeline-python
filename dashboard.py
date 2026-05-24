import streamlit as st

# ==========================================
# CONFIGURACIÓN DE PÁGINA MAESTRA
# ==========================================
# Esta configuración manda sobre todo el sistema. Se usa layout wide para acomodar gráficos.
st.set_page_config(page_title="Centro Comando HD", page_icon="🧠", layout="wide")

if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

# ==========================================
# VISTA DE LOGIN (Aislada)
# ==========================================
def pantalla_login():
    # Usamos columnas para centrar el formulario en layout wide
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown("<h1 style='text-align: center;'>🧠 Centro de Comando HD</h1>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align: center; color: gray;'>Identificación Requerida</h3>", unsafe_allow_html=True)
        st.write("") # Espaciador
        
        with st.form("login_form"):
            usuario = st.text_input("Usuario (Correo):", value="g.basso.castillo@gmail.com")
            pwd = st.text_input("Contraseña Táctica:", type="password")
            ingresar = st.form_submit_button("Desbloquear Sistema", use_container_width=True)
            
            if ingresar:
                if usuario.strip().lower() == "g.basso.castillo@gmail.com" and pwd == st.secrets["PASSWORD_MAESTRA"]:
                    st.session_state["autenticado"] = True
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas. El SNC te vigila.")

# ==========================================
# ROUTER MAESTRO (Control Inteligente de Menú)
# ==========================================
if not st.session_state["autenticado"]:
    # Si no hay sesión, la ÚNICA página es la función de login.
    # Al haber 1 sola página, Streamlit OCULTA el menú lateral automáticamente.
    pg = st.navigation([st.Page(pantalla_login, title="Autenticación", icon="🔒")])
    pg.run()
else:
    # Si hay sesión, desplegamos el menú lateral con las 3 herramientas.
    page_hip = st.Page("views/1_hipertrofia.py", title="Hipertrofia", icon="💪")
    page_nut = st.Page("views/2_nutricion.py", title="Nutrición", icon="🥩")
    page_met = st.Page("views/3_metabolismo.py", title="Metabolismo", icon="🔋")

    pg = st.navigation([page_hip, page_nut, page_met])
    pg.run()