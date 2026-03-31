import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

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
    """Mensaje de bienvenida y rescate si el usuario está perdido."""
    mensaje = (
        "🤖 *¡Sistema de Entrenamiento Interactivo!*\n\n"
        "Ya no necesitas memorizar comandos ni alias extraños.\n\n"
        "👉 Simplemente toca o escribe: `/rutina` para ver tus ejercicios de hoy y registrarlos con un par de clics."
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def respuesta_corta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Atrapalotodo cuando el usuario escribe fuera de la rutina."""
    await update.message.reply_text("⚠️ No estoy esperando datos en este momento.\nToca 👉 `/rutina` para empezar a registrar tu entrenamiento.", parse_mode="Markdown")


# --- INICIO DEL FLUJO DE TRABAJO (MÁQUINA DE ESTADOS) ---

async def mostrar_rutina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        message_obj = query.message
    else:
        message_obj = update.message

    fecha_actual = datetime.now().strftime("%d/%m/%Y")
    await message_obj.reply_text(f"⏳ Buscando tu planificación del {fecha_actual}...")

    try:
        registros = sheet.get_all_values()
        botones = []
        texto_rutina = f"🏋️‍♂️ *RUTINA DE HOY ({fecha_actual})*\n\n"

        for i, fila in enumerate(registros):
            if len(fila) > 2 and fila[0] == fecha_actual:
                ejercicio = fila[2]
                meta_reps = fila[3] if len(fila) > 3 else "-"
                meta_peso = fila[7] if len(fila) > 7 else "-"

                ya_hecho = False
                if len(fila) > 4 and fila[4].strip() not in ["", "0"]:
                    ya_hecho = True
                
                icono = "✅" if ya_hecho else "⏳"
                texto_rutina += f"{icono} *{ejercicio}*\n🎯 Meta: {meta_reps} | {meta_peso}\n\n"

                botones.append([InlineKeyboardButton(f"{icono} {ejercicio}", callback_data=str(i))])

        if not botones:
            await message_obj.reply_text(f"🤷‍♂️ Descanso. No hay nada planificado para hoy.")
            return ConversationHandler.END

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
        "Escribe tus datos en este orden separados por coma:\n"
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

    # 1. Primero agregamos la máquina de estados
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('rutina', mostrar_rutina)],
        states={
            SELECCIONANDO: [CallbackQueryHandler(boton_tocado)],
            INGRESANDO_DATOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_datos)]
        },
        fallbacks=[CommandHandler('cancelar', cancelar_conversacion)]
    )
    app.add_handler(conv_handler)

    # 2. LUEGO agregamos los comandos globales para cuando NO estás en medio de una rutina
    app.add_handler(CommandHandler("start", mostrar_ayuda))
    app.add_handler(CommandHandler("ayuda", mostrar_ayuda))
    
    # 3. Y finalmente el atrapalotodo para textos perdidos (como el "hola")
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, respuesta_corta))

    print("🤖 Servidor de Bot interactivo corriendo... ¡Ahora sí, con atrapalotodo!")
    app.run_polling()

if __name__ == '__main__':
    main()