import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 1. Definir alcance y cargar credenciales
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

# 2. Diccionario de días
dias_semana = {
    "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
    "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo"
}

try:
    # 3. Abrir la pestaña de prueba
    sheet = client.open("WORKOUT").worksheet("TESTbot")
    
    fecha_actual = datetime.now().strftime("%d/%m/%Y")
    dia_espanol = dias_semana[datetime.now().strftime("%A")]
    
    # 4. LA ESTRUCTURA CORRECTA
    # [Fecha, Día, Ejercicio, Sets x Reps, S1, S2, S3, Peso Proyectado, Notas]
    fila_prueba = [
        fecha_actual,           # Col A: Fecha
        dia_espanol,            # Col B: Día
        "Press de Prueba",      # Col C: Ejercicio
        "[De Planificación]",   # Col D: Sets x Reps (INTOCABLE)
        "12",                   # Col E: S1 (Tus reps efectivas)
        "0",                    # Col F: S2
        "0",                    # Col G: S3
        "[De Planificación]",   # Col H: Peso Proyectado (INTOCABLE)
        "Peso Real: 90kg | Calentamiento: 2 series | Obs: Certificación exitosa" # Col I: Notas
    ]
    
    sheet.append_row(fila_prueba)
    print("✅ ¡Éxito! Revisa la pestaña TESTbot. Tu peso real está en las Notas, la planificación está a salvo.")

except Exception as e:
    print(f"❌ Error al conectar: {e}")