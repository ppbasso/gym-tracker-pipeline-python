import streamlit as st

# ==========================================
# CONFIGURACIÓN DE PÁGINA MAESTRA
# ==========================================
st.set_page_config(page_title="Centro Comando HD", page_icon="🧠", layout="centered")

# ==========================================
# MÓDULO DE SEGURIDAD Y LOGIN (iOS Friendly)
# ==========================================
# ¿Por qué este diseño?: Al usar st.form y tener explícitamente un campo de "Usuario" 
# y uno de "Contraseña", forzamos al llavero de iOS (Keychain) a capturarlo.
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

if not st.session_state["autenticado"]:
    st.markdown("<h1 style='text-align: center;'>🧠 Centro de Comando HD</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center; color: gray;'>Identificación Requerida</h3>", unsafe_allow_html=True)
    
    with st.form("login_form"):
        # Campo explícito para que el iPhone ancle la contraseña a tu correo
        usuario = st.text_input("Usuario (Correo):", placeholder="g.basso.castillo@gmail.com")
        pwd = st.text_input("Contraseña Táctica:", type="password")
        ingresar = st.form_submit_button("Desbloquear Sistema")
        
        if ingresar:
            if usuario.strip().lower() == "g.basso.castillo@gmail.com" and pwd == st.secrets["PASSWORD_MAESTRA"]:
                st.session_state["autenticado"] = True
                st.success("✅ Acceso Concedido.")
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas. El SNC te vigila.")
    
    # Si no está logueado, detenemos la ejecución de la página principal aquí
    st.stop()

# ==========================================
# PORTADA DEL SISTEMA (Post-Login)
# ==========================================
# Una vez logueado, esta es la pantalla de bienvenida estática.
st.title("Bienvenido, Comandante. 🫡")
st.markdown("### Sistema Desbloqueado y Operativo.")
st.info("👈 Expande el menú lateral izquierdo y selecciona **1_Hipertrofia** para ver tu panel de fuerza.")