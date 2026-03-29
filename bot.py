import os
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 1. SEGURIDAD: Cargar variables de entorno ocultas
load_dotenv()

# 2. LOGS: Para monitorear la salud del bot en la consola
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 3. CONEXIÓN A LA BASE DE DATOS (Google Sheets)
# Definimos los permisos y cargamos el archivo JSON de forma segura
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

# Diccionario de traducción de días
DIAS_SEMANA = {
    "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
    "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo"
}

# 4. LA LÓGICA DE NEGOCIO Y ESCRITURA
async def comando_heavy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text 
    
    try:
        # A) Extracción y limpieza de variables
        datos_crudos = texto_usuario.replace("/heavy ", "")
        partes = datos_crudos.split(",")
        
        if len(partes) != 5:
            await update.message.reply_text("❌ Formato incorrecto.\nUsa: /heavy Ejercicio, Reps Efectivas, Peso Real, Calentamiento, Observación")
            return

        ejercicio = partes[0].strip()
        reps = partes[1].strip()
        peso = partes[2].strip()
        calentamiento = partes[3].strip() 
        observacion = partes[4].strip()

        fecha_actual = datetime.now().strftime("%d/%m/%Y")
        dia_espanol = DIAS_SEMANA[datetime.now().strftime("%A")]

        # B) Empaquetado de Datos Transaccionales en 'Notas'
        notas_finales = f"Peso Real: {peso}kg | Calentamiento: {calentamiento} | Obs: {observacion}"

        # C) ESCRITURA EN LA BASE DE DATOS (Producción)
        # OJO: Mantenemos la escritura en la pestaña TESTbot hasta que tú decidas cambiarlo
        sheet = client.open("WORKOUT").worksheet("TESTbot")
        
        fila_excel = [
            fecha_actual,           # Col A: Fecha
            dia_espanol,            # Col B: Día
            ejercicio,              # Col C: Ejercicio
            "[De Planificación]",   # Col D: Sets x Reps
            reps,                   # Col E: S1
            "0",                    # Col F: S2
            "0",                    # Col G: S3
            "[De Planificación]",   # Col H: Peso Proyectado
            notas_finales           # Col I: Notas
        ]
        
        # Inyectar la fila en Google Sheets
        sheet.append_row(fila_excel)

        # D) Confirmación al Usuario (Telegram)
        respuesta = (
            f"✅ ¡Guardado en Google Sheets!\n"
            f"📅 {fecha_actual} ({dia_espanol})\n"
            f"🏋️ {ejercicio}\n"
            f"📈 S1: {reps} reps\n"
            f"📝 {notas_finales}"
        )
        
        await update.message.reply_text(respuesta)

    except Exception as e:
        await update.message.reply_text(f"❌ Ocurrió un error escribiendo en la hoja: {e}")
        logging.error(f"Error detallado: {e}")

# 5. EL MOTOR DEL BOT
def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN") 
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("heavy", comando_heavy))
    print("🤖 Bot fusionado y escuchando. Enlazado a Google Sheets.")
    app.run_polling()

if __name__ == '__main__':
    main()