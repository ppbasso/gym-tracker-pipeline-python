# Gym Tracker Data Pipeline 🏋️‍♂️📊

Pipeline de ingesta de datos en tiempo real diseñado para capturar, transformar y almacenar métricas de entrenamiento físico desde una interfaz móvil (Telegram) hacia un Data Warehouse operativo (Google Sheets / BigQuery).

## 🎯 El Problema de Negocio
El registro manual de entrenamientos en aplicaciones de notas convencionales genera silos de datos, pérdida de información por scroll y requiere un retrabajo manual (Data Entry) propenso a errores para consolidar la información en hojas de cálculo para su análisis a largo plazo.

## 💡 La Solución
Se construyó un bot conversacional en Telegram respaldado por un script en Python que actúa como un motor de procesamiento. El sistema extrae las variables clave del usuario mediante comandos rápidos, aplica reglas de negocio (hardcoding dinámico, limpieza de strings, cálculo de fechas) y escribe directamente en la capa transaccional (Google Sheets) respetando un esquema de datos histórico estricto.

## 🏗️ Arquitectura de Alto Nivel

[iPhone / Telegram Web] 
       | (JSON API)
       v
[Python Script (Bot Motor)] ---> Limpieza, Transformación (Split, Formateo)
       | (Google OAuth2 / gspread)
       v
[Google Sheets / BigQuery] ---> Almacenamiento Estructurado (Data Warehouse)

## 🛠️ Stack Tecnológico
* **Lenguaje:** Python 3.14
* **Interfaces:** Telegram Bot API (`python-telegram-bot`)
* **Integración Cloud:** Google Cloud Platform (Google Drive API, Google Sheets API, `gspread`)
* **Seguridad:** Manejo de variables de entorno ocultas (`python-dotenv`) para proteger tokens y credenciales.

## 🚀 Guía de Uso Rápido
El bot responde a comandos estructurados. Ejemplo de flujo de ingesta para una rutina "Heavy Duty":

**Comando del usuario:**
`/heavy Remo con Barra, 12, 90, 2 series aprox, Cierre Q1 buenas sensaciones`

**Transformación y Carga (Payload final insertado):**
* **Ejercicio:** Remo con Barra
* **S1 (Reps Efectivas):** 12
* **Peso / Observaciones concatenadas:** Peso Real: 90kg | Calentamiento: 2 series aprox | Obs: Cierre Q1 buenas sensaciones
*(La planificación histórica se protege mediante el control de columnas en el script).*