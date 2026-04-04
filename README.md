# Gym Tracker Data Pipeline 🏋️‍♂️📊

Pipeline de ingesta de datos en tiempo real diseñado para capturar, transformar y almacenar métricas de entrenamiento físico desde una interfaz móvil interactiva (Telegram) hacia un Data Warehouse operativo (Google Sheets), preparándolo para visualización en Business Intelligence.

## 🎯 El Problema de Negocio
El registro manual de entrenamientos en aplicaciones de notas convencionales genera silos de datos, pérdida de información por scroll y requiere un retrabajo manual (Data Entry) propenso a errores para consolidar la información en hojas de cálculo para su análisis a largo plazo. 

Además, registrar datos textualmente en un smartphone durante un entrenamiento físico de alta intensidad genera una alta carga cognitiva y errores tipográficos frecuentes.

## 💡 La Solución (V2 - Arquitectura Interactiva / Telegram Bot en Render)
Se construyó un bot en Telegram respaldado por un motor asíncrono en Python alojado en **Render**. A diferencia de un bot de comandos tradicional, el sistema implementa un **Flujo Conversacional (State Machine)** que lee la planificación dinámica desde la base de datos y despliega **botones interactivos (Inline Keyboards)**. Esto reduce la fricción del usuario a cero, permitiendo registrar la hipertrofia (Peso, Reps, Notas) con clics en lugar de tipeo complejo, y escribiendo mediante **lógica de Update No Destructivo (Append)** en la capa transaccional.

Para garantizar disponibilidad 24/7 en la capa gratuita, el bot integra un micro-servidor de "Keep-Alive" monitoreado externamente por **UptimeRobot**.

> *Visualización Ingesta de Datos*
![Bot Telegram Demo](bot_demo.gif)

## 📊 La Solución (V3 - Capa de Auditoría y BI / Streamlit)
Para cerrar el ciclo de vida del dato, se construyó un Dashboard Analítico (`dashboard.py`) en **Streamlit Cloud** que actúa como un auditor implacable del rendimiento. Este panel extrae la data de Google Sheets, aplica limpieza avanzada (Regex) para aislar series efectivas y estandarizar nombres (Master Data Management), y calcula el E1RM (1 Repetición Máxima Estimada).
Cruza el **Plan (Meta)** contra la **Realidad (Ejecución)** y alerta sobre la fatiga del Sistema Nervioso Central (SNC) usando principios de entrenamiento Heavy Duty.

> *Visualización Dashboard Auditoría*
![Dashboard BI Demo](dashboard_demo.gif)

## 🏗️ Arquitectura de Alto Nivel

~~~text
[Usuario / Telegram Mobile] 
       | (JSON API / Webhooks)
       v
[Render Cloud (Python Bot)] ---> Despliegue UI Dinámica y Parsea Inputs
       |
       | (Google OAuth2 / gspread) -> Lógica de Append
       v
[Google Sheets (Data Warehouse)] <--- Capa de Almacenamiento Central
       |
       | (Pandas / Regex ETL) -> Limpieza, MDM y Cálculo E1RM
       v
[Streamlit + Altair Dashboard] ---> Visualización Front-End, Radar SNC y Gráficos Duales
~~~

## 🧠 Características Técnicas Destacadas
* **Máquina de Estados (ConversationHandler):** Control estricto de la interacción del bot.
* **Acceso a Datos O(1):** Mapeo dinámico del `index` de la fila (`callback_data`) para escrituras directas.
* **Update No Destructivo (Append):** El código lee el estado actual de la celda de observaciones antes de escribir, concatenando los nuevos registros de peso y sensaciones sin destruir el histórico.
* **Inteligencia de Datos (MDM & Regex):** El motor ETL resuelve identidades (Alias de ejercicios) y prioriza la serie efectiva pesada (S3 > S2 > S1) ignorando el ruido de los calentamientos.
* **Lógica de "Descarga Global":** Detección automática de semanas de descanso para evitar falsos positivos en los cálculos de estancamiento.
* **Disponibilidad 24/7:** Sistema de Keep-Alive mediante servidor HTTP interno para evitar la suspensión del servicio en capas gratuitas monitoreado por **UptimeRobot**.
* **UI Adaptativa y Accesible:** Gráficos Altair de alto contraste sin interpolaciones confusas, diseñados bajo enfoque Mobile-First.

## 🛠️ Stack Tecnológico
* **Lenguaje:** Python 3.10+
* **Infraestructura:** Render (Bot), Streamlit Cloud (Dashboard), UptimeRobot (Uptime Monitor).
* **Ingesta:** Telegram Bot API (`python-telegram-bot` v20+)
* **Procesamiento (ETL):** `pandas`, `numpy`, `re` (Expresiones Regulares)
* **Visualización:** `streamlit`, `altair`
* **Integración Cloud:** Google Cloud Platform (Google Sheets API, `gspread`)

## 🚀 Guía de Uso Rápido
1. **Ingesta:** Usa el comando `/rutina` en Telegram. Responde a los botones interactivos con el formato: `Reps, Peso, Calentamiento, Obs`.
2. **Visualización:** Accede a la URL en Streamlit Cloud (o ejecuta `streamlit run dashboard.py` en local) para auditar el cumplimiento del bloque, la recuperación del SNC y visualizar los gráficos de meta vs realidad.