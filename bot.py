import os
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
# FASE 1: CONEXIÓN A GOOGLE SHEETS
# ==========================================
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
client = gspread.authorize(creds)

sheet = client.open_by_key("1oVmaWg-i4onBq9l8Nkql1mBXRUhAWO_kkH93Bda78tI").worksheet("TESTbot")

# ==========================================
# FASE 2: ESTADOS DE LA CONVERSACIÓN
# ==========================================
SELECCIONANDO, INGRESANDO_DATOS = range(2)

# ==========================================
# FASE 3: LÓGICA DEL BOT (UX Y NAVEGACIÓN)
# ==========================================

async def mostrar_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida oficial."""
    mensaje = (
        "🤖 *¡Sistema de Entrenamiento Interactivo!*\n\n"
        "👉 Toca o escribe: `/rutina` para ver tus ejercicios de hoy y registrarlos con un par de clics."
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def educar_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Atrapalotodo global: Atrapa comandos huérfanos (/cancelar, /heavy) o textos (hola)."""
    mensaje = "⚠️ *Comando o texto no reconocido.*\n\n👉 Por favor, usa el comando `/rutina` para interactuar con tu planificación."
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def boton_expirado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Atrapalotodo para botones zombis de sesiones anteriores."""
    query = update.callback_query
    # query.answer detiene el circulito de carga en Telegram. show_alert lanza un pop-up.
    await query.answer("Esta botonera ha expirado ❌", show_alert=True)
    await query.message.reply_text("⚠️ *Botón Expirado*\nEse menú es antiguo o el bot se reinició. Escribe `/rutina` para generar uno nuevo.", parse_mode="Markdown")


# --- INICIO DEL FLUJO DE TRABAJO (MÁQUINA DE ESTADOS) ---

async def mostrar_rutina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        message_obj = query.message
    else:
        message_obj = update.message

    # Guardamos la fecha actual matemática para poder comparar después
    fecha_actual_dt = datetime.now()
    fecha_actual_str = fecha_actual_dt.strftime("%d/%m/%Y")
    
    await message_obj.reply_text(f"⏳ Buscando tu planificación del {fecha_actual_str}...")

    try:
        registros = sheet.get_all_values()
        botones = []
        texto_rutina = f"🏋️‍♂️ *RUTINA DE HOY ({fecha_actual_str})*\n\n"

        for i, fila in enumerate(registros):
            if len(fila) > 2 and fila[0] == fecha_actual_str:
                ejercicio = fila[2]
                meta_reps = fila[3] if len(fila) > 3 else "-"
                meta_peso = fila[7] if len(fila) > 7 else "-"

                ya_hecho = False
                if len(fila) > 4 and fila[4].strip() not in ["", "0"]:
                    ya_hecho = True
                
                icono = "✅" if ya_hecho else "⏳"
                texto_rutina += f"{icono} *{ejercicio}*\n🎯 Meta: {meta_reps} | {meta_peso}\n\n"

                botones.append([InlineKeyboardButton(f"{icono} {ejercicio}", callback_data=str(i))])

        # NUEVA LÓGICA: Si no hay entrenamiento hoy, buscar el próximo
        if not botones:
            proxima_fecha = None
            for fila in registros:
                if len(fila) > 0:
                    try:
                        # Convertimos el texto del Excel a tiempo matemático
                        fecha_fila = datetime.strptime(fila[0], "%d/%m/%Y")
                        # Preguntamos si la fecha de la fila es MAYOR que la de hoy
                        if fecha_fila.date() > fecha_actual_dt.date():
                            proxima_fecha = fila[0]
                            break # Encontramos el más cercano, detenemos la búsqueda
                    except ValueError:
                        continue # Si hay una fila vacía o con texto raro en vez de fecha, la ignoramos
            
            if proxima_fecha:
                await message_obj.reply_text(f"🤷‍♂️ Descanso. No hay nada planificado para hoy.\n🗓️ *Tu próximo entrenamiento es el:* {proxima_fecha}", parse_mode="Markdown")
            else:
                await message_obj.reply_text(f"🤷‍♂️ Descanso. Y no encontré más entrenamientos en el futuro de tu Excel.")
                
            return ConversationHandler.END

        # Si hay botones, agregamos el de cancelar y mandamos el menú
        botones.append([InlineKeyboardButton("❌ Finalizar Entrenamiento", callback_data="cancelar")])
        reply_markup = InlineKeyboardMarkup(botones)
        await message_obj.reply_text(texto_rutina, reply_markup=reply_markup, parse_mode="Markdown")
        
        return SELECCIONANDO

    except Exception as e:
        await message_obj.reply_text(f"❌ Error al leer Google Sheets: {e}")
        return ConversationHandler.END


async def boton_tocado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar":
        await query.edit_message_text("💪 ¡Entrenamiento finalizado por hoy! Gran trabajo.")
        return ConversationHandler.END

    fila_idx = int(query.data)
    context.user_data['fila_actual'] = fila_idx + 1

    registros = sheet.get_all_values()
    ejercicio = registros[fila_idx][2]
    context.user_data['ejercicio_actual'] = ejercicio

    mensaje = (
        f"📍 Seleccionaste: *{ejercicio}*\n\n"
        "Escribe tus datos separados por coma:\n"
        "`Reps, Peso, Calentamiento, Obs`\n\n"
        "*(Ej: 12, 30, 2 series, contracción brutal)*\n\n"
        "✍️ Ingresa los datos ahora (o manda /cancelar para volver atrás):"
    )
    await query.edit_message_text(mensaje, parse_mode="Markdown")
    
    return INGRESANDO_DATOS


async def procesar_datos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()

    if texto.lower() == "/cancelar":
        await update.message.reply_text("Volviendo a la rutina...")
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
        
        return await mostrar_rutina(update, context)

    except Exception as e:
        await update.message.reply_text(f"❌ Error al guardar en Sheets: {e}")
        return ConversationHandler.END

async def cancelar_conversacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada. Usa /rutina cuando estés listo.")
    return ConversationHandler.END


# ==========================================
# FASE 4: ARRANQUE DEL SERVIDOR
# ==========================================
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    app = Application.builder().token(token).build()

    # 1. LA MÁQUINA DE ESTADOS (Lo más importante primero)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('rutina', mostrar_rutina)],
        states={
            SELECCIONANDO: [CallbackQueryHandler(boton_tocado)],
            INGRESANDO_DATOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_datos)]
        },
        fallbacks=[CommandHandler('cancelar', cancelar_conversacion), CommandHandler('rutina', mostrar_rutina)]
    )
    app.add_handler(conv_handler)

    # 2. COMANDOS BÁSICOS 
    app.add_handler(CommandHandler("start", mostrar_ayuda))
    app.add_handler(CommandHandler("ayuda", mostrar_ayuda))
    
    # 3. ATRAPALOTODO DE BOTONES ZOMBIS (Debe ir fuera del ConversationHandler)
    app.add_handler(CallbackQueryHandler(boton_expirado))

    # 4. ATRAPALOTODO GLOBAL (Mensajes, comandos basura, etc.)
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, educar_usuario))

    # --- LÍNEA AGREGADA 2 (PARA RENDER) ---
    keep_alive()

    print("🤖 Servidor de Bot interactivo corriendo... ¡A prueba de fallos!")
    app.run_polling()

if __name__ == '__main__':
    main()