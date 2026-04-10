import os
import re # <--- AÑADIDA: Librería para buscar patrones de texto (Regex)
from functools import wraps # <--- AÑADIDA: Para crear el guardia de seguridad (Decorador)
from datetime import datetime, timedelta # <--- AÑADIDA: timedelta para manipulación de fechas
import time # <--- AÑADIDA: Control de concurrencia para evitar crashes en Render
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

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

# ==========================================
# FASE 2: ESTADOS DE LA CONVERSACIÓN
# ==========================================
# Ampliamos los estados para cubrir el módulo de entrenamiento, biometría y reagendamiento
SELECCIONANDO, INGRESANDO_DATOS, INGRESANDO_MEDICIONES, POSPONER_ORIGEN, POSPONER_DESTINO = range(5)

# ==========================================
# FASE 2.5: MOTOR FORENSE (HISTÓRICO Y PREVENCIÓN)
# ==========================================
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
            
        return f"\n_🕰️ Último válido ({fecha_valida}): {reps} reps x {peso_real} kg_"
    
    return "" 

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
        "👉 Toca /posponer para reorganizar tu agenda de entrenamiento."
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")

@requiere_admin
async def educar_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = "⚠️ *Comando no reconocido.*\n\n👉 Usa /rutina, /medidas o /posponer."
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
    
    hoy = datetime.now().date()
    fechas_pendientes = set()
    
    try:
        registros = sheet.get_all_values()
        for fila in registros:
            if len(fila) > 2:
                try:
                    fecha_fila = datetime.strptime(fila[0], "%d/%m/%Y").date()
                    # Solo nos interesan fechas de hoy en adelante
                    if fecha_fila >= hoy:
                        ya_hecho = len(fila) > 4 and fila[4].strip() not in ["", "0"]
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
    
    hoy = datetime.now().date()
    
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
                ya_hecho = len(fila) > 4 and fila[4].strip() not in ["", "0"]
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
    if query:
        await query.answer()
        message_obj = query.message
    else:
        message_obj = update.message

    fecha_actual_dt = datetime.now()
    fecha_actual_str = fecha_actual_dt.strftime("%d/%m/%Y")
    context.user_data['fecha_actual'] = fecha_actual_str 
    
    await message_obj.reply_text(f"⏳ Buscando tu planificación del {fecha_actual_str}...")

    try:
        registros = sheet.get_all_values()
        botones = []
        texto_rutina = f"🏋️‍♂️ *RUTINA DE HOY ({fecha_actual_str})*\n\n"
        
        tiene_entrenamiento_hoy = False
        todos_hechos = True
        primer_pendiente_idx = None
        primer_pendiente_nombre = None

        for i, fila in enumerate(registros): # <--- CORRECCIÓN DEL SYNTAX ERROR AQUÍ
            if len(fila) > 2 and fila[0] == fecha_actual_str:
                tiene_entrenamiento_hoy = True
                ejercicio = fila[2]
                meta_reps = fila[3] if len(fila) > 3 else "-"
                meta_peso = fila[7] if len(fila) > 7 else "-"
                nota_plan = fila[8] if len(fila) > 8 else ""

                ya_hecho = False
                if len(fila) > 4 and fila[4].strip() not in ["", "0"]:
                    ya_hecho = True
                
                icono = "✅" if ya_hecho else "⏳"
                texto_rutina += f"{icono} *{ejercicio}*\n🎯 Meta: {meta_reps} | {meta_peso}\n📝 Notas: {nota_plan}\n\n"

                if not ya_hecho and primer_pendiente_idx is None:
                    todos_hechos = False
                    primer_pendiente_idx = i
                    primer_pendiente_nombre = ejercicio

        if not tiene_entrenamiento_hoy:
            proxima_fecha = None
            for fila in registros:
                if len(fila) > 0:
                    try:
                        fecha_fila = datetime.strptime(fila[0], "%d/%m/%Y")
                        if fecha_fila.date() > fecha_actual_dt.date():
                            proxima_fecha = fila[0]
                            break 
                    except ValueError:
                        continue 
            
            if proxima_fecha:
                await message_obj.reply_text(f"🤷‍♂️ Descanso. No hay nada planificado para hoy.\n🗓️ *Tu próximo entrenamiento es el:* {proxima_fecha}", parse_mode="Markdown")
            else:
                await message_obj.reply_text(f"🤷‍♂️ Descanso. Y no encontré más entrenamientos en el futuro de tu Excel.")
                
            return ConversationHandler.END

        if not todos_hechos:
            botones.append([InlineKeyboardButton(f"▶️ {primer_pendiente_nombre}", callback_data=str(primer_pendiente_idx))])
        
        botones.append([InlineKeyboardButton("❌ Finalizar Entrenamiento", callback_data="cancelar")])
        reply_markup = InlineKeyboardMarkup(botones)
        
        await message_obj.reply_text(texto_rutina, reply_markup=reply_markup, parse_mode="Markdown")
        
        return SELECCIONANDO

    except Exception as e:
        await message_obj.reply_text(f"❌ Error al leer Google Sheets: {e}")
        return ConversationHandler.END

@requiere_admin
async def boton_tocado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar":
        await query.edit_message_text("💪 ¡Entrenamiento finalizado por hoy! Gran trabajo.")
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

    fecha_actual_str = context.user_data.get('fecha_actual', datetime.now().strftime("%d/%m/%Y"))
    historial_str = get_ultimo_registro_valido(registros, ejercicio, fecha_actual_str)

    mensaje = (
        f"📍 *EJERCICIO:* {ejercicio} 🎯 *META:* {meta_reps} | {meta_peso}\n"
        f"📝 *NOTA:* {nota_plan}{historial_str}\n\n"
        "Reps, Peso, Calentamiento, Obs *(Ej: 12, 30, 2 series, contracción brutal)*\n"
        "✍️ Ingresa datos ahora (o /cancelar para volver):"
    )
    await query.edit_message_text(mensaje, parse_mode="Markdown")
    
    return INGRESANDO_DATOS

@requiere_admin
async def procesar_datos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()

    if texto.lower() == "/cancelar":
        await update.message.reply_text("Volviendo al resumen de rutina...")
        return await mostrar_rutina(update, context)

    partes = texto.split(",", 3) 
    
    if len(partes) != 4:
        await update.message.reply_text("❌ Formato incorrecto. Necesito 4 datos (Reps, Peso, Calentamiento, Obs).\nIntenta de nuevo:")
        return INGRESANDO_DATOS 

    reps, peso, calentamiento, observacion = [p.strip() for p in partes]
    
    fila = context.user_data['fila_actual']
    ejercicio = context.user_data['ejercicio_actual']

    await update.message.reply_text(f"⏳ Guardando *{ejercicio}*...", parse_mode="Markdown")

    try:
        celda_obs = sheet.acell(f'I{fila}').value
        obs_actual = celda_obs.strip() if celda_obs else ""

        nueva_nota = f"Calentamiento: {calentamiento} | Peso real: {peso}kg | Obs: {observacion}"
        notas_finales = f"{obs_actual} {nueva_nota}" if obs_actual else nueva_nota

        sheet.update_acell(f'E{fila}', reps)
        sheet.update_acell(f'I{fila}', notas_finales)

        await update.message.reply_text(f"✅ ¡Guardado perfecto!")
        
        fecha_actual_str = context.user_data.get('fecha_actual', datetime.now().strftime("%d/%m/%Y"))
        registros = sheet.get_all_values()
        siguiente_idx = None
        
        for i, fila_datos in enumerate(registros):
            if len(fila_datos) > 2 and fila_datos[0] == fecha_actual_str:
                ya_hecho = len(fila_datos) > 4 and fila_datos[4].strip() not in ["", "0"]
                if not ya_hecho:
                    siguiente_idx = i
                    break 
                    
        if siguiente_idx is not None:
            fila_datos = registros[siguiente_idx]
            sig_ejercicio = fila_datos[2]
            sig_meta_reps = fila_datos[3] if len(fila_datos) > 3 else "-"
            sig_meta_peso = fila_datos[7] if len(fila_datos) > 7 else "-"
            sig_nota_plan = fila_datos[8] if len(fila_datos) > 8 else "-"
            
            context.user_data['fila_actual'] = siguiente_idx + 1
            context.user_data['ejercicio_actual'] = sig_ejercicio
            
            historial_str = get_ultimo_registro_valido(registros, sig_ejercicio, fecha_actual_str)

            await update.message.reply_text(f"⏳ Buscando el siguiente ejercicio de tu planificación del {fecha_actual_str}...")
            
            mensaje = (
                f"📍 *EJERCICIO:* {sig_ejercicio} 🎯 *META:* {sig_meta_reps} | {sig_meta_peso}\n"
                f"📝 *NOTA:* {sig_nota_plan}{historial_str}\n\n"
                "Reps, Peso, Calentamiento, Obs *(Ej: 12, 30, 2 series, contracción brutal)*\n"
                "✍️ Ingresa datos ahora (o /cancelar para volver):"
            )
            await update.message.reply_text(mensaje, parse_mode="Markdown")
            return INGRESANDO_DATOS
        else:
            return await mostrar_rutina(update, context)

    except Exception as e:
        await update.message.reply_text(f"❌ Error al guardar en Sheets: {e}")
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

    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
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

@requiere_admin
async def cancelar_conversacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada. Usa /rutina, /medidas o /posponer cuando estés listo.")
    return ConversationHandler.END


# ==========================================
# FASE 4: ARRANQUE DEL SERVIDOR
# ==========================================
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    app = Application.builder().token(token).build()

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

    # 4. COMANDOS BÁSICOS 
    app.add_handler(CommandHandler("start", mostrar_ayuda))
    app.add_handler(CommandHandler("ayuda", mostrar_ayuda))
    
    # 5. ATRAPALOTODO DE BOTONES ZOMBIS
    app.add_handler(CallbackQueryHandler(boton_expirado))

    # 6. ATRAPALOTODO GLOBAL
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