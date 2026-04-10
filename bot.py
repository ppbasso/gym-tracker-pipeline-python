import os
import re # <--- AÑADIDA: Librería para buscar patrones de texto (Regex)
from functools import wraps # <--- AÑADIDA: Para crear el guardia de seguridad (Decorador)
from datetime import datetime
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
# Añadimos un tercer estado para el nuevo túnel de biometría
SELECCIONANDO, INGRESANDO_DATOS, INGRESANDO_MEDICIONES = range(3)

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
    """Mensaje de bienvenida oficial actualizado con el nuevo comando."""
    mensaje = (
        "🤖 *¡Sistema de Comando Heavy Duty!*\n\n"
        "👉 Toca /rutina para iniciar tu entrenamiento.\n"
        "👉 Toca /medidas para registrar tu biometría corporal."
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")

@requiere_admin
async def educar_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = "⚠️ *Comando no reconocido.*\n\n👉 Usa /rutina para entrenar o /medidas para biometría."
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def boton_expirado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Esta botonera ha expirado ❌", show_alert=True)
    await query.message.reply_text("⚠️ *Botón Expirado*\nEse menú es antiguo o el bot se reinició. Escribe /rutina para generar uno nuevo.", parse_mode="Markdown")


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

        for i, fila in enumerate(registros):
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
    """Recibe la data, valida la longitud y la anexa a la hoja Mediciones."""
    texto = update.message.text.strip()
    
    if texto.lower() == "/cancelar":
        await update.message.reply_text("📏 Operación de biometría cancelada.")
        return ConversationHandler.END

    partes = [p.strip() for p in texto.split(",")]
    
    # Validación estricta: Deben ser exactamente 9 valores (excluyendo la fecha)
    if len(partes) != 9:
        await update.message.reply_text(
            f"❌ *Error de Formato:*\nEsperaba 9 datos, pero detecté {len(partes)}.\n"
            "Asegúrate de separar todo con comas. Intenta de nuevo:"
        )
        return INGRESANDO_MEDICIONES

    # Generamos la fecha/hora exacta de la ingesta
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    # Construimos la fila: [Fecha, Peso, Cuello...]
    fila_nueva = [ahora] + partes

    await update.message.reply_text("⏳ Sincronizando biometría con el Data Warehouse...")

    try:
        # append_row inyecta los datos en la primera fila vacía al final del documento
        sheet_mediciones.append_row(fila_nueva)
        await update.message.reply_text("✅ ¡Métricas corporales guardadas exitosamente!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al guardar en Sheets: {e}")

    return ConversationHandler.END

@requiere_admin
async def cancelar_conversacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada. Usa /rutina o /medidas cuando estés listo.")
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

    # 2. LA MÁQUINA DE ESTADOS (Módulo de Biometría - Aislado)
    conv_mediciones = ConversationHandler(
        entry_points=[CommandHandler('medidas', iniciar_mediciones)],
        states={
            INGRESANDO_MEDICIONES: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_mediciones)]
        },
        fallbacks=[CommandHandler('cancelar', cancelar_conversacion), CommandHandler('medidas', iniciar_mediciones)]
    )
    app.add_handler(conv_mediciones)

    # 3. COMANDOS BÁSICOS 
    app.add_handler(CommandHandler("start", mostrar_ayuda))
    app.add_handler(CommandHandler("ayuda", mostrar_ayuda))
    
    # 4. ATRAPALOTODO DE BOTONES ZOMBIS
    app.add_handler(CallbackQueryHandler(boton_expirado))

    # 5. ATRAPALOTODO GLOBAL
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, educar_usuario))

    # --- LÍNEA AGREGADA 2 (PARA RENDER) ---
    keep_alive()

    print("🤖 Servidor de Bot interactivo corriendo... ¡A prueba de fallos!")
    app.run_polling()

if __name__ == '__main__':
    main()