import os
import re # <--- AÑADIDA: Librería para buscar patrones de texto (Regex)
import json # <--- AÑADIDA: Para decodificar la respuesta JSON del INTA
from functools import wraps # <--- AÑADIDA: Para crear el guardia de seguridad (Decorador)
from datetime import datetime, timedelta # <--- AÑADIDA: timedelta para manipulación de fechas
import time # <--- AÑADIDA: Control de concurrencia para evitar crashes en Render
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from zoneinfo import ZoneInfo # <--- AÑADIDA: Librería nativa para control de husos horarios (DST)
from google import genai # <--- AÑADIDA: Motor de Inteligencia del INTA
from google.genai import types # <--- AÑADIDA: Motor de Inteligencia del INTA
# --- LÍNEA AGREGADA 1 (PARA RENDER) ---
from keep_alive import keep_alive

load_dotenv()

# ==========================================
# FASE 0: SEGURIDAD Y CONTROL DE ACCESO
# ==========================================
# Carga tu ID desde el archivo .env. Si no existe, usa 0 (nadie entra).
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

def requiere_admin(func):
    """
    Decorador (Guardia de Seguridad). 
    Se ejecuta ANTES de la función a la que protege. Si el ID no coincide,
    bloquea la ejecución y lanza una alerta. Si coincide, te deja pasar.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            print(f"⚠️ INTRUSO DETECTADO: ID {user_id} intentó usar el bot.")
            mensaje_bloqueo = "⛔ *SNC Security:* Acceso denegado. No eres el comandante autorizado."
            
            if update.message:
                await update.message.reply_text(mensaje_bloqueo, parse_mode="Markdown")
            elif update.callback_query:
                await update.callback_query.answer("Acceso Denegado ⛔", show_alert=True)
            
            return ConversationHandler.END # Expulsa al usuario
        
        return await func(update, context, *args, **kwargs) # Todo ok, pasa a la función real
    return wrapper


# ==========================================
# FASE 1: CONEXIÓN A GOOGLE SHEETS
# ==========================================
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
client = gspread.authorize(creds)

# Conectamos a las dos pestañas de tu Data Warehouse
sheet = client.open_by_key("1oVmaWg-i4onBq9l8Nkql1mBXRUhAWO_kkH93Bda78tI").worksheet("TESTbot")
sheet_mediciones = client.open_by_key("1oVmaWg-i4onBq9l8Nkql1mBXRUhAWO_kkH93Bda78tI").worksheet("Mediciones")
sheet_nutricion = client.open_by_key("1oVmaWg-i4onBq9l8Nkql1mBXRUhAWO_kkH93Bda78tI").worksheet("Nutricion")

# Inicialización del Cerebro INTA Enjaulado
cliente_ia = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

PROMPT_MAESTRO_INTA = """
Tu única fuente de verdad es la 'Tabla de Composición Química de Alimentos Chilenos del INTA' (Universidad de Chile) y la base de datos de LATINFOODS/FAO, los cuales tienes integrados en tu memoria nativa.
El usuario enviará un texto describiendo lo que comió. Calcula calorías y macros siguiendo estas reglas de interpretación chilena:
1. 'Una marraqueta' o 'marraqueta' a secas equivale estrictamente a 2 dientes sueltos (50g totales).
2. 'Media marraqueta' equivale a 1 diente (25g). 'Dos marraquetas' equivale a 4 dientes (100g).
3. 'Un italiano' o 'un as' en contexto de calle se mapea como 'Completo Italiano Estándar' o 'As de Vacuno Italiano'.
4. 'Plato de casino' o 'un plato' de comida casera toma la porción de referencia estándar del INTA.

Si el texto ingresado no tiene relación con comida, responde exactamente: {"error": "No mapeado"}

Devuelve ÚNICAMENTE un objeto JSON estructurado, sin texto extra, sin formato markdown, con este formato exacto:
{"calorias": 0, "proteinas": 0, "grasas": 0, "carbohidratos": 0, "alimento_detectado": "Nombre y porcion"}
"""

# ==========================================
# FASE 2: ESTADOS DE LA CONVERSACIÓN
# ==========================================
# Ampliamos los estados para cubrir el módulo de entrenamiento, biometría, reagendamiento y nutrición
SELECCIONANDO, INGRESANDO_DATOS, INGRESANDO_MEDICIONES, POSPONER_ORIGEN, POSPONER_DESTINO, ESPERANDO_COMIDA = range(6)

# ==========================================
# FASE 2.5: MOTOR FORENSE Y UX (MINIMALISMO)
# ==========================================
def acortar_nombre(nombre, mantener_banco=False):
    """Función táctica para limpiar texto en pantallas pequeñas. Interruptor de banco incluido."""
    nombre_limpio = nombre.strip()
    
    if not mantener_banco:
        # 1. Elimina posiciones del banco (ej: "(4)", "(7)") visualmente solo si está apagado el switch
        nombre_limpio = re.sub(r'\s*\(\d+\)', '', nombre_limpio).strip()
    
    # 2. Reemplazos tácticos de lectura
    if "Press con Mancuernas Plano" in nombre_limpio:
        return nombre_limpio.replace("Press con Mancuernas Plano", "Press Plano [M] 🦾")
    
    nombre_limpio = nombre_limpio.replace(" con Mancuernas", " [M] 🦾")
    nombre_limpio = nombre_limpio.replace(" con Mancuerna", " [M] 🦾")
    nombre_limpio = nombre_limpio.replace(" con Barra", " [B] 🏋️")
    
    return nombre_limpio

def extract_real_weight_bot(peso_proyectado_str, nota_str):
    """Extrae el peso real levantado usando la misma lógica ETL del dashboard."""
    base_w_str = str(peso_proyectado_str).lower().replace('kg', '').strip()
    try: base_w = float(base_w_str)
    except: base_w = 0.0

    nota = str(nota_str).lower()

    for prefix in ['peso real:', 'peso real', 'sigo con', 'estoy con']:
        if prefix in nota:
            m = re.search(rf'{prefix}\s*(\d+\.?\d*)', nota)
            if m: return float(m.group(1))

    m_serie = re.search(r'serie.*?(\d+\.?\d*)\s*kg', nota)
    if m_serie: return float(m_serie.group(1))

    m_con = re.search(r'con\s*(\d+\.?\d*)\s*kg', nota)
    if m_con: return float(m_con.group(1))

    return base_w

def get_ultimo_registro_valido(registros, target_ejercicio, current_date_str):
    """Busca hacia atrás la última sesión efectiva, saltándose fechas de descarga completas."""
    fechas_descarga = set()
    for fila in registros:
        if len(fila) > 8 and 'descarga' in fila[8].lower():
            fechas_descarga.add(fila[0])

    try:
        current_date = datetime.strptime(current_date_str, "%d/%m/%Y")
    except ValueError:
        return "" 
    
    ultimo_registro = None
    
    for fila in registros:
        if len(fila) > 2 and fila[2].strip() == target_ejercicio.strip():
            try:
                fila_date = datetime.strptime(fila[0], "%d/%m/%Y")
                if fila_date < current_date and fila[0] not in fechas_descarga:
                    ultimo_registro = fila
            except ValueError:
                continue
                
    if ultimo_registro:
        fecha_valida = ultimo_registro[0][:5] 
        reps = ultimo_registro[4] if len(ultimo_registro) > 4 and ultimo_registro[4].strip() else "0"
        peso_proy = ultimo_registro[7] if len(ultimo_registro) > 7 else "0"
        nota = ultimo_registro[8] if len(ultimo_registro) > 8 else ""
        
        peso_real = extract_real_weight_bot(peso_proy, nota)
        
        if float(peso_real).is_integer():
            peso_real = int(peso_real)
            
        # FORMATO MINIMALISTA V2.0
        return f"\n🕰️ Últ.({fecha_valida}): {reps} reps x {peso_real} kg"
    
    return "" 

def es_ejercicio_hecho(fila):
    """Función táctica: Diferencia un '0' pendiente por defecto de un '0' saltado por el usuario."""
    if len(fila) <= 4: return False
    reps_str = str(fila[4]).strip()
    tiene_reps = reps_str not in ["", "0"]
    
    firma_bot = False
    if len(fila) > 8:
        firma_bot = "Peso real:" in str(fila[8])
        
    return tiene_reps or firma_bot

# --- TODO: DEUDA TÉCNICA - MIGRAR A BD ---
# Diccionario táctico (Hotfix) para inyectar rutinas de calentamiento específicas en la UX.
WARMUP_HOTFIX = {
    "Press con Mancuernas Plano": "1x15 16KG",
    "Goblet Squat con Mancuerna": "1x20 Peso Corporal",
    "Remo con Barra": "1x20 20KG, 1x6 60KG"
}
# -----------------------------------------


# ==========================================
# FASE 3: LÓGICA DEL BOT (UX Y NAVEGACIÓN)
# ==========================================

@requiere_admin
async def mostrar_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida oficial actualizado."""
    mensaje = (
        "🤖 *¡Sistema de Comando Heavy Duty!*\n\n"
        "👉 Toca /rutina para iniciar tu entrenamiento.\n"
        "👉 Toca /medidas para registrar tu biometría corporal.\n"
        "👉 Toca /posponer para reorganizar tu agenda de entrenamiento.\n"
        "👉 Usa `/comer` para registrar tus macros."
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")

@requiere_admin
async def educar_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = "⚠️ *Comando no reconocido.*\n\n👉 Usa /rutina, /medidas, /posponer o el comando /comer."
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def boton_expirado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Esta botonera ha expirado ❌", show_alert=True)
    await query.message.reply_text("⚠️ *Botón Expirado*\nEse menú es antiguo o el bot se reinició.", parse_mode="Markdown")


# --- NUEVO FLUJO LOGÍSTICO: /posponer (MÁQUINA DE ESTADOS) ---

@requiere_admin
async def iniciar_posponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 1: Escanea la DB y muestra los días disponibles para mover."""
    await update.message.reply_text("⏳ Analizando tu calendario de entrenamientos pendientes...")
    
    # HUSO HORARIO CLOUD-NATIVE: Resiliencia ante DST Chileno
    hoy = datetime.now(ZoneInfo("America/Santiago")).date()
    fechas_pendientes = set()
    
    try:
        registros = sheet.get_all_values()
        for fila in registros:
            if len(fila) > 2:
                try:
                    fecha_fila = datetime.strptime(fila[0], "%d/%m/%Y").date()
                    # Solo nos interesan fechas de hoy en adelante
                    if fecha_fila >= hoy:
                        ya_hecho = es_ejercicio_hecho(fila)
                        if not ya_hecho:
                            fechas_pendientes.add(fecha_fila)
                except ValueError:
                    continue
        
        if not fechas_pendientes:
            await update.message.reply_text("🤷‍♂️ No tienes entrenamientos futuros pendientes en tu agenda.")
            return ConversationHandler.END
            
        # Ordenar cronológicamente y tomar las próximas 4 sesiones
        fechas_ordenadas = sorted(list(fechas_pendientes))[:4]
        
        botones = []
        for d in fechas_ordenadas:
            d_str = d.strftime("%d/%m/%Y")
            botones.append([InlineKeyboardButton(f"📅 {d_str}", callback_data=f"orig_{d_str}")])
            
        botones.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_posponer")])
        
        await update.message.reply_text(
            "📋 *¿Qué entrenamiento deseas posponer?*",
            reply_markup=InlineKeyboardMarkup(botones),
            parse_mode="Markdown"
        )
        return POSPONER_ORIGEN

    except Exception as e:
        await update.message.reply_text(f"❌ Error al leer Google Sheets: {e}")
        return ConversationHandler.END

@requiere_admin
async def origen_posponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 2: Captura el origen y pregunta el destino."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancelar_posponer":
        await query.edit_message_text("❌ Reagendamiento cancelado.")
        return ConversationHandler.END
        
    # Extraemos la fecha del CallbackData (Ej: "orig_10/04/2026")
    fecha_origen = query.data.split("_")[1]
    context.user_data['fecha_origen_posponer'] = fecha_origen
    
    botones = [
        [InlineKeyboardButton("Mañana (+1 día)", callback_data="dest_manana")],
        [InlineKeyboardButton("Pasado Mañana (+2 días)", callback_data="dest_pasado")],
        [InlineKeyboardButton("Próximo Lunes", callback_data="dest_lunes")],
        [InlineKeyboardButton("Próximo Viernes", callback_data="dest_viernes")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_posponer")]
    ]
    
    await query.edit_message_text(
        f"📅 Has seleccionado el entrenamiento del *{fecha_origen}*.\n\n"
        "¿Para cuándo deseas moverlo?",
        reply_markup=InlineKeyboardMarkup(botones),
        parse_mode="Markdown"
    )
    return POSPONER_DESTINO

@requiere_admin
async def destino_posponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 3: Calcula la matemática, inyecta la nueva fecha y cierra el flujo."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_posponer":
        await query.edit_message_text("❌ Reagendamiento cancelado.")
        return ConversationHandler.END

    fecha_origen = context.user_data['fecha_origen_posponer']
    destino_tipo = query.data.split("_")[1]
    
    # HUSO HORARIO CLOUD-NATIVE
    hoy = datetime.now(ZoneInfo("America/Santiago")).date()
    
    # Cálculos matemáticos precisos del calendario
    if destino_tipo == "manana":
        nueva_fecha = hoy + timedelta(days=1)
    elif destino_tipo == "pasado":
        nueva_fecha = hoy + timedelta(days=2)
    elif destino_tipo == "lunes":
        dias_para_lunes = (0 - hoy.weekday() + 7) % 7
        if dias_para_lunes == 0: dias_para_lunes = 7 # Si hoy es lunes, salta al próximo
        nueva_fecha = hoy + timedelta(days=dias_para_lunes)
    elif destino_tipo == "viernes":
        dias_para_viernes = (4 - hoy.weekday() + 7) % 7
        if dias_para_viernes == 0: dias_para_viernes = 7 # Si hoy es viernes, salta al próximo
        nueva_fecha = hoy + timedelta(days=dias_para_viernes)

    nueva_fecha_str = nueva_fecha.strftime("%d/%m/%Y")

    await query.edit_message_text(f"⚙️ Moviendo rutina del {fecha_origen} al {nueva_fecha_str}...")

    try:
        registros = sheet.get_all_values()
        filas_a_modificar = []

        # Buscamos todas las filas con la fecha de origen que no estén hechas
        for i, fila in enumerate(registros):
            if len(fila) > 2 and fila[0] == fecha_origen:
                ya_hecho = es_ejercicio_hecho(fila)
                if not ya_hecho:
                    filas_a_modificar.append(i + 1)

        # Disparo en ráfaga a Google Sheets
        for num_fila in filas_a_modificar:
            sheet.update_acell(f'A{num_fila}', nueva_fecha_str)

        await query.edit_message_text(
            f"✅ *¡Operación Táctica Exitosa!*\n\n"
            f"Tu rutina del {fecha_origen} ha sido trasladada oficialmente al *{nueva_fecha_str}*.\n"
            "Data Warehouse actualizado.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Error crítico al escribir en Google Sheets: {e}")

    return ConversationHandler.END


# --- INICIO DEL FLUJO DE ENTRENAMIENTO (/rutina) ---

@requiere_admin
async def mostrar_rutina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # HUSO HORARIO CLOUD-NATIVE
    fecha_actual_dt = datetime.now(ZoneInfo("America/Santiago"))
    fecha_actual_str = fecha_actual_dt.strftime("%d/%m/%Y")
    context.user_data['fecha_actual'] = fecha_actual_str 

    # --- MODO FANTASMA: Tracking del Mensaje Maestro ---
    if not query and update.message and update.message.text == "/rutina":
        # Disparo limpio desde cero. Limpiamos variables de sesiones viejas.
        context.user_data.pop('tiempo_inicio', None)
        reply = await update.message.reply_text(f"⏳ Buscando tu planificación del {fecha_actual_str}...")
        context.user_data['main_msg_id'] = reply.message_id
    elif query:
        await query.answer()
        await query.edit_message_text(f"⏳ Buscando tu planificación del {fecha_actual_str}...")
    elif context.user_data.get('main_msg_id'):
        # Retorno desde un error o cancelación (Editando el msg maestro)
        try:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=context.user_data['main_msg_id'], text=f"⏳ Buscando tu planificación del {fecha_actual_str}...")
        except: pass

    try:
        registros = sheet.get_all_values()
        
        tiene_entrenamiento_hoy = False
        todos_hechos = True
        primer_pendiente_idx = None
        primer_pendiente_nombre = None
        primer_ejercicio_dia = None
        total_ejercicios = 0
        ejercicios_hechos = 0
        lista_visual = ""

        # Escaneo y Análisis del Día
        for i, fila in enumerate(registros):
            if len(fila) > 2 and fila[0] == fecha_actual_str:
                tiene_entrenamiento_hoy = True
                total_ejercicios += 1
                ejercicio = fila[2]
                
                if not primer_ejercicio_dia: 
                    primer_ejercicio_dia = ejercicio

                ya_hecho = es_ejercicio_hecho(fila)
                if ya_hecho:
                    ejercicios_hechos += 1
                
                icono = "✅" if ya_hecho else "⏳"
                # Usamos False para limpiar la visual del banco en el menú resumen
                lista_visual += f"{icono} {acortar_nombre(ejercicio, mantener_banco=False)}\n"

                if not ya_hecho and primer_pendiente_idx is None:
                    todos_hechos = False
                    primer_pendiente_idx = i
                    primer_pendiente_nombre = ejercicio

        context.user_data['total_ejercicios'] = total_ejercicios
        context.user_data['ejercicios_hechos'] = ejercicios_hechos

        # Manejo de Descansos
        if not tiene_entrenamiento_hoy:
            proxima_fecha = None
            for fila in registros:
                if len(fila) > 0:
                    try:
                        fecha_fila = datetime.strptime(fila[0], "%d/%m/%Y")
                        if fecha_fila.date() > fecha_actual_dt.date():
                            proxima_fecha = fila[0]
                            break 
                    except ValueError: continue 
            
            msg_descanso = f"🤷‍♂️ Descanso. No hay nada planificado para hoy.\n🗓️ *Tu próximo entrenamiento es el:* {proxima_fecha}" if proxima_fecha else "🤷‍♂️ Descanso. No encontré más rutinas."
            
            if context.user_data.get('main_msg_id'):
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=context.user_data['main_msg_id'], text=msg_descanso, parse_mode="Markdown")
            return ConversationHandler.END

        # Título Dinámico (Alpha/Omega)
        titulo_rutina = "🏋️‍♂️ RUTINA DE HOY"
        if primer_ejercicio_dia:
            if "Press con Mancuernas Plano" in primer_ejercicio_dia: titulo_rutina = "🐺 Rutina Alpha"
            elif "Remo con Barra" in primer_ejercicio_dia: titulo_rutina = "Ω Rutina Omega"

        texto_final = f"*{titulo_rutina}*\n📝 {total_ejercicios} Ejercicios\n\n{lista_visual}"
        
        botones = []
        if not todos_hechos:
            botones.append([InlineKeyboardButton(f"▶️ Iniciar ({ejercicios_hechos + 1}/{total_ejercicios})", callback_data=str(primer_pendiente_idx))])
        
        botones.append([InlineKeyboardButton("❌ Cerrar", callback_data="cancelar")])
        reply_markup = InlineKeyboardMarkup(botones)
        
        if context.user_data.get('main_msg_id'):
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=context.user_data['main_msg_id'], text=texto_final, reply_markup=reply_markup, parse_mode="Markdown")
        
        return SELECCIONANDO

    except Exception as e:
        if context.user_data.get('main_msg_id'):
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=context.user_data['main_msg_id'], text=f"❌ Error al leer Google Sheets: {e}")
        return ConversationHandler.END

@requiere_admin
async def boton_tocado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar":
        await query.edit_message_text("💪 Menú de entrenamiento cerrado. ¡Gran trabajo!")
        return ConversationHandler.END

    fila_idx = int(query.data)
    context.user_data['fila_actual'] = fila_idx + 1

    registros = sheet.get_all_values()
    fila_datos = registros[fila_idx]
    
    ejercicio = fila_datos[2]
    meta_reps = fila_datos[3] if len(fila_datos) > 3 else "-"
    meta_peso = fila_datos[7] if len(fila_datos) > 7 else "-"
    nota_plan = fila_datos[8] if len(fila_datos) > 8 else "-"
    
    context.user_data['ejercicio_actual'] = ejercicio
    # HUSO HORARIO CLOUD-NATIVE
    fecha_actual_str = context.user_data.get('fecha_actual', datetime.now(ZoneInfo("America/Santiago")).strftime("%d/%m/%Y"))
    
    # Minimalismo UI v2.0 - Encendemos el interruptor True para ver el Banco
    ej_acortado = acortar_nombre(ejercicio, mantener_banco=True)
    total_ejs = context.user_data.get('total_ejercicios', '?')
    ej_num = context.user_data.get('ejercicios_hechos', 0) + 1
    
    historial_str = get_ultimo_registro_valido(registros, ejercicio, fecha_actual_str)
    warmup_str = f"\n🔥 WARMUP: {WARMUP_HOTFIX[ejercicio]}" if ejercicio in WARMUP_HOTFIX else ""

    # RADAR: Motor de Búsqueda Up Next
    sig_ejercicio = None
    for i in range(fila_idx + 1, len(registros)):
        if len(registros[i]) > 2 and registros[i][0] == fecha_actual_str:
            if not es_ejercicio_hecho(registros[i]):
                sig_ejercicio = registros[i][2]
                break
    up_next_str = f"\n🔜 {acortar_nombre(sig_ejercicio, mantener_banco=True)}" if sig_ejercicio else ""

    mensaje = (
        f"📍 {ej_num}/{total_ejs} {ej_acortado}\n"
        f"🎯 {meta_reps} | {meta_peso}\n"
        f"📝 {nota_plan}{historial_str}{warmup_str}{up_next_str}\n"
        "✍️ Ingresar o /cancelar:\n"
        "Calentamiento, Peso, Reps, Obs"
    )
    await query.edit_message_text(mensaje, parse_mode="Markdown")
    
    return INGRESANDO_DATOS

@requiere_admin
async def procesar_datos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    chat_id = update.effective_chat.id

    # --- MODO FANTASMA: Destrucción del mensaje del usuario ---
    try: await update.message.delete()
    except: pass

    if texto.lower() == "/cancelar":
        return await mostrar_rutina(update, context)

    # --- CRONÓMETRO TÁCTICO ---
    # Solo se dispara si es el primer ejercicio ingresado en esta sesión.
    if 'tiempo_inicio' not in context.user_data:
        context.user_data['tiempo_inicio'] = datetime.now(ZoneInfo("America/Santiago"))

    partes = texto.split(",", 3) 
    
    if len(partes) != 4:
        msg_error = "❌ Formato incorrecto. Necesito 4 datos separados por comas.\nEj: 0, 30, 10, ok"
        if context.user_data.get('main_msg_id'):
            try: await context.bot.edit_message_text(chat_id=chat_id, message_id=context.user_data['main_msg_id'], text=msg_error)
            except: pass
        return INGRESANDO_DATOS 

    calentamiento, peso, reps, observacion = [p.strip() for p in partes]
    
    # --- BLOQUEO DE CERO ORDENADO POR EL COMANDANTE ---
    if str(reps) == "0":
        msg_error = "⚠️ *WARNING:* No ingreses '0' en repeticiones, el bot no lo entenderá y colapsará. Si deseas saltar el ejercicio, debes hacerlo manualmente en Google Sheets. Ingresa datos reales:\nCalentamiento, Peso, Reps, Obs"
        if context.user_data.get('main_msg_id'):
            try: await context.bot.edit_message_text(chat_id=chat_id, message_id=context.user_data['main_msg_id'], text=msg_error, parse_mode="Markdown")
            except: pass
        return INGRESANDO_DATOS
        
    fila = context.user_data['fila_actual']
    ejercicio = context.user_data['ejercicio_actual']

    # Feedback intermedio (Sobrescribe en la misma burbuja)
    if context.user_data.get('main_msg_id'):
        try: await context.bot.edit_message_text(chat_id=chat_id, message_id=context.user_data['main_msg_id'], text=f"⏳ Guardando *{acortar_nombre(ejercicio, mantener_banco=False)}*...", parse_mode="Markdown")
        except: pass

    try:
        celda_obs = sheet.acell(f'I{fila}').value
        obs_actual = celda_obs.strip() if celda_obs else ""

        nueva_nota = f"Calentamiento: {calentamiento} | Peso real: {peso}kg | Obs: {observacion}"
        notas_finales = f"{obs_actual} {nueva_nota}" if obs_actual else nueva_nota

        sheet.update_acell(f'E{fila}', reps)
        sheet.update_acell(f'I{fila}', notas_finales)

        # Recargamos para buscar el siguiente
        # HUSO HORARIO CLOUD-NATIVE
        fecha_actual_str = context.user_data.get('fecha_actual', datetime.now(ZoneInfo("America/Santiago")).strftime("%d/%m/%Y"))
        registros = sheet.get_all_values()

        # --- PARCHE DE LATENCIA (EVENTUAL CONSISTENCY) ---
        # Forzamos la actualización en memoria local inmediata por si Google Sheets tarda en refrescar el READ.
        if len(registros) >= fila:
            while len(registros[fila - 1]) <= 8:
                registros[fila - 1].append("")
            registros[fila - 1][4] = str(reps)
            registros[fila - 1][8] = notas_finales

        siguiente_idx = None
        
        # Aumentamos el contador interno de hechos
        context.user_data['ejercicios_hechos'] = context.user_data.get('ejercicios_hechos', 0) + 1
        
        for i, fila_datos in enumerate(registros):
            if len(fila_datos) > 2 and fila_datos[0] == fecha_actual_str:
                ya_hecho = es_ejercicio_hecho(fila_datos)
                if not ya_hecho:
                    siguiente_idx = i
                    break 
                    
        if siguiente_idx is not None:
            # FLUJO: MOSTRAR SIGUIENTE EJERCICIO
            fila_datos = registros[siguiente_idx]
            sig_ejercicio = fila_datos[2]
            meta_reps = fila_datos[3] if len(fila_datos) > 3 else "-"
            meta_peso = fila_datos[7] if len(fila_datos) > 7 else "-"
            nota_plan = fila_datos[8] if len(fila_datos) > 8 else "-"
            
            context.user_data['fila_actual'] = siguiente_idx + 1
            context.user_data['ejercicio_actual'] = sig_ejercicio
            
            ej_acortado = acortar_nombre(sig_ejercicio, mantener_banco=True)
            total_ejs = context.user_data.get('total_ejercicios', '?')
            ej_num = context.user_data.get('ejercicios_hechos', 0) + 1
            
            historial_str = get_ultimo_registro_valido(registros, sig_ejercicio, fecha_actual_str)
            warmup_str = f"\n🔥 {WARMUP_HOTFIX[sig_ejercicio]}" if sig_ejercicio in WARMUP_HOTFIX else ""

            # RADAR: Motor de Búsqueda Up Next
            sig_sig_ejercicio = None
            for i in range(siguiente_idx + 1, len(registros)):
                if len(registros[i]) > 2 and registros[i][0] == fecha_actual_str:
                    if not es_ejercicio_hecho(registros[i]):
                        sig_sig_ejercicio = registros[i][2]
                        break
            up_next_str = f"\n🔜 {acortar_nombre(sig_sig_ejercicio, mantener_banco=True)}" if sig_sig_ejercicio else ""

            mensaje = (
                f"📍 {ej_num}/{total_ejs} {ej_acortado}\n"
                f"🎯 {meta_reps} | {meta_peso}\n"
                f"📝 {nota_plan}{historial_str}{warmup_str}{up_next_str}\n"
                "✍️ Ingresar o /cancelar:\n"
                "Calentamiento, Peso, Reps, Obs"
            )
            
            if context.user_data.get('main_msg_id'):
                await context.bot.edit_message_text(chat_id=chat_id, message_id=context.user_data['main_msg_id'], text=mensaje, parse_mode="Markdown")
            return INGRESANDO_DATOS
            
        else:
            # FLUJO: ENTRENAMIENTO FINALIZADO (SUMARIO FANTASMA)
            # HUSO HORARIO CLOUD-NATIVE
            tiempo_inicio = context.user_data.get('tiempo_inicio', datetime.now(ZoneInfo("America/Santiago")) - timedelta(minutes=45))
            minutos = int((datetime.now(ZoneInfo("America/Santiago")) - tiempo_inicio).total_seconds() / 60)
            if minutos < 1: minutos = 1

            # PARCHADO: Nuevo UI del Sumario
            sumario = f"⏱️🦾🏋️ Sesión: {minutos} Minutos.\n"
            
            for f in registros:
                if len(f) > 8 and f[0] == fecha_actual_str:
                    ya_hecho = es_ejercicio_hecho(f)
                    if ya_hecho:
                        # Apagamos el banco para mantener el sumario final ultra limpio
                        ej_a = acortar_nombre(f[2], mantener_banco=False)
                        reps_r = f[4]
                        
                        # Forense Extractor de las Notas Recién Guardadas
                        nota_real = f[8]
                        m_peso = re.search(r'Peso real:\s*(.*?)(?:kg|\s*\|)', nota_real)
                        peso_str = m_peso.group(1).strip() if m_peso else "0"
                        
                        m_cal = re.search(r'Calentamiento:\s*(.*?)\s*\|', nota_real)
                        cal_str = m_cal.group(1).strip() if m_cal else ""
                        str_cal = f" 🔥 {cal_str}" if cal_str and cal_str.lower() not in ["0", "none", "", "no"] else ""
                        
                        sumario += f"✅ {ej_a} 1x{reps_r} {peso_str}kg{str_cal}\n"

            if context.user_data.get('main_msg_id'):
                await context.bot.edit_message_text(chat_id=chat_id, message_id=context.user_data['main_msg_id'], text=sumario, parse_mode="Markdown")
            
            context.user_data.clear() # Limpieza total de RAM
            return ConversationHandler.END

    except Exception as e:
        if context.user_data.get('main_msg_id'):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=context.user_data['main_msg_id'], text=f"❌ Error crítico: {e}")
        return ConversationHandler.END


# --- INICIO DEL FLUJO DE BIOMETRÍA (/medidas) ---

@requiere_admin
async def iniciar_mediciones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activa el módulo de recolección de métricas corporales."""
    mensaje = (
        "📏 *MÓDULO DE BIOMETRÍA*\n\n"
        "Ingresa tus 9 métricas separadas por comas en este orden exacto:\n"
        "`Peso, Cuello, Pecho, Cintura, Cadera, BrazoI, BrazoD, MusloI, MusloD`\n\n"
        "💡 *Ejemplo de copiado rápido:*\n"
        "`98.5, 42, 115, 108, 107, 33, 33, 60.5, 62`\n\n"
        "✍️ Ingresa los datos ahora (o /cancelar para abortar):"
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")
    return INGRESANDO_MEDICIONES

@requiere_admin
async def guardar_mediciones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe la data, valida la longitud y la inyecta con precisión quirúrgica."""
    texto = update.message.text.strip()
    
    if texto.lower() == "/cancelar":
        await update.message.reply_text("📏 Operación de biometría cancelada.")
        return ConversationHandler.END

    partes = [p.strip() for p in texto.split(",")]
    
    if len(partes) != 9:
        await update.message.reply_text(
            f"❌ *Error de Formato:*\nEsperaba 9 datos, pero detecté {len(partes)}.\n"
            "Asegúrate de separar todo con comas. Intenta de nuevo:"
        )
        return INGRESANDO_MEDICIONES

    # HUSO HORARIO CLOUD-NATIVE
    ahora = datetime.now(ZoneInfo("America/Santiago")).strftime("%d/%m/%Y %H:%M")
    fila_nueva = [ahora] + partes

    await update.message.reply_text("⏳ Sincronizando biometría con precisión...")

    try:
        # LÓGICA DE FRANCOTIRADOR: 
        # 1. Obtenemos todos los valores de la Columna A (Fechas)
        columna_fechas = sheet_mediciones.col_values(1)
        # 2. Eliminamos los vacíos por si hay celdas fantasma entre medio
        fechas_reales = [f for f in columna_fechas if f.strip() != ""]
        # 3. La fila correcta es la cantidad de fechas reales + 1
        siguiente_fila = len(fechas_reales) + 1
        
        # 4. Inyectamos la lista como una fila nueva en el rango exacto
        rango = f'A{siguiente_fila}:J{siguiente_fila}'
        sheet_mediciones.update(values=[fila_nueva], range_name=rango)
        
        await update.message.reply_text("✅ ¡Métricas corporales guardadas exitosamente en la fila correcta!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al guardar en Sheets: {e}")

    return ConversationHandler.END


# ==========================================
# FASE 3.1: MÓDULO DE NUTRICIÓN SOBERANA INTA (/comer)
# ==========================================

@requiere_admin
async def iniciar_comer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 1: Decide si procesa de inmediato o pregunta qué comiste."""
    # Extrae cualquier texto que venga después del comando /comer
    entrada = update.message.text.replace('/comer', '').strip()
    
    if entrada:
        # Opción A: Modo Rápido ("/comer 3 italianos")
        return await procesar_comida_logica(update, context, entrada)
    else:
        # Opción B: Modo Asistido (El usuario solo apretó /comer)
        msg = await update.message.reply_text("📝 ¿Qué comiste? (Escribe tu comida o usa /cancelar)")
        # Guardamos el ID para luego editar y mantener el Timeline limpio
        context.user_data['msg_comer_id'] = msg.message_id
        return ESPERANDO_COMIDA

@requiere_admin
async def recibir_comida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 2 (Solo Modo Asistido): Captura el texto sin comandos."""
    entrada = update.message.text.strip()
    
    if entrada.lower() == '/cancelar':
        await update.message.reply_text("✅ Registro de comida cancelado.")
        return ConversationHandler.END
        
    return await procesar_comida_logica(update, context, entrada)

async def procesar_comida_logica(update: Update, context: ContextTypes.DEFAULT_TYPE, entrada_usuario: str):
    """El Motor Principal: Dispara a IA, Maneja el 503 y Actualiza Sheets."""
    chat_id = update.effective_chat.id
    
    # --- MODO FANTASMA: Destrucción de la burbuja del usuario ---
    try: await update.message.delete()
    except: pass
    
    # Si venimos del Modo Asistido, editamos esa burbuja. Si no, creamos una nueva.
    if 'msg_comer_id' in context.user_data:
        try:
            reply = await context.bot.edit_message_text(
                chat_id=chat_id, 
                message_id=context.user_data['msg_comer_id'], 
                text="⏳ Procesando con el motor INTA..."
            )
        except:
            reply = await context.bot.send_message(chat_id=chat_id, text="⏳ Procesando con el motor INTA...")
    else:
        reply = await context.bot.send_message(chat_id=chat_id, text="⏳ Procesando con el motor INTA...")

    # Operación Google Sheets: Buscamos la fila correcta primero
    ahora_chile = datetime.now(ZoneInfo("America/Santiago")).strftime("%d/%m/%Y %H:%M")
    try:
        columna_fechas = sheet_nutricion.col_values(1)
        fechas_reales = [f for f in columna_fechas if f.strip() != ""]
        siguiente_fila = len(fechas_reales) + 1
    except Exception as e:
        await reply.edit_text(f"❌ Error de base de datos: No pude leer el Excel. {e}")
        return ConversationHandler.END

    try:
        # INTENTO AL MOTOR GOOGLE
        response = cliente_ia.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{PROMPT_MAESTRO_INTA}\n\nUsuario informa: '{entrada_usuario}'",
            config=types.GenerateContentConfig(temperature=0.0)
        )
        texto_limpio = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(texto_limpio)
        
        if "error" in data:
            await reply.edit_text("❌ Alimento o porción fuera de la cobertura del INTA.")
            return ConversationHandler.END

        # ÉXITO IA: Guardamos todo (Fecha, Nombre, Original, Macros)
        fila_alimentaria = [
            ahora_chile, 
            data['alimento_detectado'], 
            entrada_usuario, 
            data['calorias'], 
            data['proteinas'], 
            data['grasas'], 
            data['carbohidratos']
        ]
        sheet_nutricion.update(values=[fila_alimentaria], range_name=f'A{siguiente_fila}:G{siguiente_fila}')
        
        # Mantenemos el chat a 1 sola burbuja
        await reply.edit_text(
            f"✅ **Mapeo INTA Exitoso**\n🔍 Detectado: {data['alimento_detectado']}\n\n"
            f"🔥 Kcal: {data['calorias']} | 🥩 P: {data['proteinas']}g | 🥑 G: {data['grasas']}g | 🍚 C: {data['carbohidratos']}g",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        print(f"⚠️ Error IA Nutrición (Posible 503): {e}")
        # ESCUDO ANTI-503: Caemos aquí si Google nos rechaza.
        # Guardamos solo Fecha, Original y dejamos Macros vacíos.
        fila_offline = [ahora_chile, "", entrada_usuario, "", "", "", ""]
        try:
            sheet_nutricion.update(values=[fila_offline], range_name=f'A{siguiente_fila}:G{siguiente_fila}')
            await reply.edit_text("⚠️ Mapeo offline. Tu comida está guardada en la base.\nTe notificaré cuando quede calculada.")
        except Exception as sheet_err:
            await reply.edit_text(f"❌ Fallo crítico absoluto. Ni IA ni Sheets respondieron: {sheet_err}")

    # Limpiamos RAM
    context.user_data.pop('msg_comer_id', None)
    return ConversationHandler.END


@requiere_admin
async def cancelar_conversacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada. Usa /rutina, /medidas o /posponer cuando estés listo.")
    return ConversationHandler.END


# ==========================================
# FASE 3.2: HERRAMIENTAS DE DESARROLLADOR (DEV TOOLS)
# ==========================================
@requiere_admin
async def revisar_cola(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /cola: El botón de pánico para auditar fallos 503."""
    await update.message.reply_text("🔍 Escaneando base de datos en busca de comidas encoladas...")
    try:
        registros = sheet_nutricion.get_all_values()
        pendientes = []
        # Saltamos el encabezado (i=0)
        for i, fila in enumerate(registros):
            if i == 0: continue
            
            # Condición de cola: Columna C (Descripción) tiene texto, pero Columna D (Calorías) está vacía
            if len(fila) >= 3 and str(fila[2]).strip() != "":
                calorias = str(fila[3]).strip() if len(fila) > 3 else ""
                if not calorias:
                    pendientes.append(fila[2])
                    
        if pendientes:
            lista = "\n".join([f"• {p}" for p in pendientes])
            await update.message.reply_text(f"⏳ Tienes {len(pendientes)} comidas esperando a Google:\n\n{lista}")
        else:
            await update.message.reply_text("✅ La cola está limpia. Todo ha sido calculado.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al auditar la cola: {e}")


# ==========================================
# FASE 3.5: MOTOR DE TAREAS EN SEGUNDO PLANO (JOBQUEUE)
# ==========================================

async def sabueso_nutricion(context: ContextTypes.DEFAULT_TYPE):
    """
    Se ejecuta cada 10 minutos buscando filas sin macros.
    Si encuentra una, dispara a la IA de forma invisible y notifica.
    """
    if not ADMIN_ID: return

    try:
        registros = sheet_nutricion.get_all_values()
        # Iteramos saltando el encabezado
        for i, fila in enumerate(registros):
            if i == 0: continue
            
            if len(fila) >= 3 and str(fila[2]).strip() != "":
                calorias = str(fila[3]).strip() if len(fila) > 3 else ""
                
                # ¡ENCONTRAMOS UNA FILA ATASCADA!
                if not calorias:
                    texto_comida = fila[2]
                    print(f"[SABUESO] 🔍 Detectado registro offline: '{texto_comida}'. Intentando resolver...")
                    
                    try:
                        # Golpe a la IA
                        response = cliente_ia.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=f"{PROMPT_MAESTRO_INTA}\n\nUsuario informa: '{texto_comida}'",
                            config=types.GenerateContentConfig(temperature=0.0)
                        )
                        texto_limpio = response.text.replace('```json', '').replace('```', '').strip()
                        data = json.loads(texto_limpio)
                        
                        if "error" not in data:
                            # Mapeo exitoso: Escribimos celda por celda (Google Sheets usa índice 1 para filas)
                            num_fila = i + 1 
                            sheet_nutricion.update_acell(f'B{num_fila}', data['alimento_detectado'])
                            sheet_nutricion.update_acell(f'D{num_fila}', data['calorias'])
                            sheet_nutricion.update_acell(f'E{num_fila}', data['proteinas'])
                            sheet_nutricion.update_acell(f'F{num_fila}', data['grasas'])
                            sheet_nutricion.update_acell(f'G{num_fila}', data['carbohidratos'])
                            
                            # Dispara el push a tu teléfono
                            msg = (f"✅ **Mapeo INTA Exitoso (Automático)**\n"
                                   f"🔍 Detectado: {data['alimento_detectado']} (de '{texto_comida}')\n\n"
                                   f"🔥 Kcal: {data['calorias']} | 🥩 P: {data['proteinas']}g | 🥑 G: {data['grasas']}g | 🍚 C: {data['carbohidratos']}g")
                            await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")
                            print(f"[SABUESO] ✅ Resuelto y notificado: '{texto_comida}'")
                            
                            # Break táctico: Procesamos 1 sola fila atascada por ciclo (cada 10 min) 
                            # para no ahogar la API de Google si hay muchas juntas.
                            break 
                    except Exception as ia_err:
                        print(f"[SABUESO] ⚠️ Fallo silencioso al procesar '{texto_comida}' (Posible 503). Reintento en 10 min. Detalle: {ia_err}")
                        break # Corta el bucle para no seguir chocando con el muro
    except Exception as e:
        print(f"[SABUESO] ❌ Error crítico leyendo Google Sheets: {e}")


async def motor_notificaciones(context: ContextTypes.DEFAULT_TYPE):
    """
    Función silenciosa que corre cada hora en el servidor.
    Se ajusta a la zona horaria de Chile usando zoneinfo nativo para no fallar con el horario de verano.
    """
    if not ADMIN_ID:
        return # Si no hay ID configurado, aborta para no causar errores

    # HUSO HORARIO CLOUD-NATIVE: Inmune a DST
    ahora_chile = datetime.now(ZoneInfo("America/Santiago"))
    hora_actual = ahora_chile.hour

    # Compuerta Táctica: Solo consultamos Google Sheets en las horas exactas de las alarmas
    if hora_actual not in [11, 19]:
        return

    try:
        registros = sheet.get_all_values()
        hoy_str = ahora_chile.strftime("%d/%m/%Y")
        manana_str = (ahora_chile + timedelta(days=1)).strftime("%d/%m/%Y")

        entrena_hoy = False
        entrena_manana = False
        primer_ejercicio_manana = ""
        
        # Leemos el Excel para ver si hoy o mañana hay filas de entrenamiento sin completar
        for fila in registros:
            if len(fila) > 2:
                ya_hecho = es_ejercicio_hecho(fila)
                if not ya_hecho:
                    if fila[0] == hoy_str:
                        entrena_hoy = True
                    elif fila[0] == manana_str:
                        entrena_manana = True
                        if not primer_ejercicio_manana:
                            primer_ejercicio_manana = fila[2]

        comandos_tacticos = "\n\n👉 Comandos rápidos: /rutina | /posponer | /medidas"

        # REGLA 1: Mañana a las 11:00 (Día de entrenamiento)
        if hora_actual == 11 and entrena_hoy:
            msg = "🔥 *ALERTA DE IGNICIÓN.*\n\nTienes entrenamiento a las 13:00. Activa el pre-entreno mental." + comandos_tacticos
            await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")

        # REGLA 2: Mañana a las 11:00 (Día de descanso)
        elif hora_actual == 11 and not entrena_hoy:
            msg = "🛡️ *ESCUDO DE RECUPERACIÓN.*\n\nHoy es día de descanso. Mantente alejado de las pesas. El crecimiento ocurre fuera del gimnasio, no adentro." + comandos_tacticos
            await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")

        # REGLA 3: Noche anterior a las 19:00
        elif hora_actual == 19 and entrena_manana:
            msg = f"⚡ *ALERTA DE PREPARACIÓN.*\n\nMañana te toca entrenamiento (Iniciando con: {primer_ejercicio_manana}). Prepara tu bolso, la comida y duerme al menos 7 horas." + comandos_tacticos
            await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")

    except Exception as e:
        print(f"Error silencioso en motor de notificaciones: {e}")


# ==========================================
# FASE 4: ARRANQUE DEL SERVIDOR
# ==========================================
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    app = Application.builder().token(token).build()

    # --- INYECCIÓN JOBQUEUE ---
    # 1. Alarma de Entrenamiento: Corre cada 3600 segs (1 hora)
    app.job_queue.run_repeating(motor_notificaciones, interval=3600, first=10)
    # 2. Sabueso de Nutrición: Corre cada 600 segs (10 minutos)
    app.job_queue.run_repeating(sabueso_nutricion, interval=600, first=30)

    # 1. LA MÁQUINA DE ESTADOS (Módulo de Entrenamiento)
    conv_rutina = ConversationHandler(
        entry_points=[CommandHandler('rutina', mostrar_rutina)],
        states={
            SELECCIONANDO: [CallbackQueryHandler(boton_tocado)],
            INGRESANDO_DATOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_datos)]
        },
        fallbacks=[CommandHandler('cancelar', cancelar_conversacion), CommandHandler('rutina', mostrar_rutina)]
    )
    app.add_handler(conv_rutina)

    # 2. LA MÁQUINA DE ESTADOS (Módulo de Biometría)
    conv_mediciones = ConversationHandler(
        entry_points=[CommandHandler('medidas', iniciar_mediciones)],
        states={
            INGRESANDO_MEDICIONES: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_mediciones)]
        },
        fallbacks=[CommandHandler('cancelar', cancelar_conversacion), CommandHandler('medidas', iniciar_mediciones)]
    )
    app.add_handler(conv_mediciones)

    # 3. LA MÁQUINA DE ESTADOS (Módulo Logístico: Posponer)
    conv_posponer = ConversationHandler(
        entry_points=[CommandHandler('posponer', iniciar_posponer)],
        states={
            POSPONER_ORIGEN: [CallbackQueryHandler(origen_posponer)],
            POSPONER_DESTINO: [CallbackQueryHandler(destino_posponer)]
        },
        fallbacks=[CommandHandler('cancelar', cancelar_conversacion)]
    )
    app.add_handler(conv_posponer)

    # 4. LA MÁQUINA DE ESTADOS (Módulo Nutrición Soberana)
    conv_comer = ConversationHandler(
        entry_points=[CommandHandler('comer', iniciar_comer)],
        states={
            ESPERANDO_COMIDA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_comida)]
        },
        fallbacks=[CommandHandler('cancelar', cancelar_conversacion)]
    )
    app.add_handler(conv_comer)

    # 5. COMANDOS DEV Y BÁSICOS 
    app.add_handler(CommandHandler("cola", revisar_cola))
    app.add_handler(CommandHandler("start", mostrar_ayuda))
    app.add_handler(CommandHandler("ayuda", mostrar_ayuda))
    
    # 6. ATRAPALOTODO DE BOTONES ZOMBIS
    app.add_handler(CallbackQueryHandler(boton_expirado))

    # 7. ATRAPALOTODO GLOBAL
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, educar_usuario))

    # --- LÍNEA AGREGADA 2 (PARA RENDER) ---
    keep_alive()

    # --- SOLUCIÓN DE FONDO PARA OVERLAP DE RENDER ---
    print("⏳ Retraso táctico de 12s para evitar colisión de despliegues en Render...")
    time.sleep(12) 

    print("🤖 Servidor de Bot interactivo corriendo... ¡A prueba de fallos!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()