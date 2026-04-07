# Gym Tracker Data Pipeline 🏋️‍♂️📊

Pipeline de ingesta de datos en tiempo real diseñado para capturar, transformar y almacenar métricas de entrenamiento físico desde una interfaz móvil interactiva (Telegram) hacia un Data Warehouse operativo (Google Sheets), preparándolo para visualización en Business Intelligence.

## 🎯 El Problema de Negocio
El registro manual de entrenamientos en aplicaciones de notas convencionales genera silos de datos, pérdida de información por scroll y requiere un retrabajo manual (Data Entry) propenso a errores para consolidar la información en hojas de cálculo para su análisis a largo plazo. 

Además, registrar datos textualmente en un smartphone durante un entrenamiento físico de alta intensidad genera una alta carga cognitiva y errores tipográficos frecuentes.

## 💡 La Solución (V2 - Arquitectura Interactiva / Telegram Bot en Render)
Se construyó un bot en Telegram respaldado por un motor asíncrono en Python alojado en **Render**. A diferencia de un bot de comandos tradicional, el sistema implementa un **Flujo Conversacional (State Machine)** con lógica de **Linear Stepper (Auto-avance)**. El bot lee la planificación dinámica, agrupa las metas y notas tácticas de cada ejercicio, y guía al usuario de forma secuencial. Esto elimina la necesidad de navegar por menús durante el entrenamiento, permitiendo registrar la hipertrofia (Peso, Reps, Notas) sin fricción y escribiendo mediante **lógica de Update No Destructivo (Append)** en la capa transaccional.

Para garantizar disponibilidad 24/7 en la capa gratuita, el bot integra un micro-servidor de "Keep-Alive" monitoreado externamente por **UptimeRobot**.

> *Visualización Ingesta de Datos*
<br>
<img src="bot_demo.gif" width="300" alt="Bot Telegram Demo">

## 📊 La Solución (V3 - Capa de Auditoría y BI / Streamlit)
Para cerrar el ciclo de vida del dato, se construyó un Dashboard Analítico (`dashboard.py`) en **Streamlit Cloud** que actúa como un auditor implacable del rendimiento. Este panel extrae la data de Google Sheets, aplica limpieza avanzada (Regex) para aislar series efectivas y estandarizar nombres (Master Data Management), y calcula el E1RM (1 Repetición Máxima Estimada).
Cruza el **Plan (Meta)** contra la **Realidad (Ejecución)** y alerta sobre la fatiga del Sistema Nervioso Central (SNC) usando principios de entrenamiento Heavy Duty.

> *Visualización Dashboard Auditoría*
<br>
<img src="dashboard_demo.gif" width="300" alt="Dashboard BI Demo">

## 🏗️ Arquitectura de Alto Nivel

~~~text
[Usuario / Telegram Mobile] 
       | (JSON API / Webhooks)
       v
[Render Cloud (Python Bot)] ---> Despliegue UI Dinámica, Motor Forense y Parsea Inputs
       |
       | (Google OAuth2 / gspread) -> Lógica de Append
       v
[Google Sheets (Data Warehouse)] <--- Capa de Almacenamiento Central
       |
       | (Pandas / Regex ETL) -> Limpieza, MDM y Cálculo E1RM
       v
[Streamlit + Altair Dashboard] ---> Visualización Front-End, Motor Dual y Radar SNC
~~~

## 🧠 Características Técnicas Destacadas
* **Motor Forense (Contexto Histórico):** Algoritmo de retroceso temporal que escanea el Data Warehouse para inyectar la última marca válida (Reps x Peso real extraído vía Regex) directamente en la UI del bot, aislando y descartando heurísticamente semanas de "descarga" completas para garantizar la sobrecarga progresiva sin riesgo de lesiones.
* **Motor de Renderizado Dual (BI):** Arquitectura de visualización bifurcada en Streamlit que permite auditar la data bajo dos enfoques analíticos: un eje **Biomecánico** (Grupos Musculares aislados con protección contra Falsos Positivos) o un eje **Operativo** basado en listas deterministas (Módulo Alpha / Módulo Omega), haciendo el análisis agnóstico a los días de la semana.
* **Linear Stepper (Auto-Avance UX):** Algoritmo de escaneo en tiempo real que detecta el próximo ejercicio vacío y autogestiona la transición, eliminando la navegación manual de menús en entornos de alta intensidad física.
* **Update No Destructivo (Append):** El código lee el estado actual de la celda de observaciones antes de escribir, concatenando los nuevos registros de peso y sensaciones sin destruir el histórico.
* **Inteligencia de Datos (MDM):** El motor ETL resuelve identidades (Alias de ejercicios) y prioriza la serie efectiva pesada (S3 > S2 > S1) ignorando el ruido de los calentamientos.
* **Disponibilidad 24/7 y Sincronización Temporal:** Sistema de Keep-Alive compatible con método `HEAD` de UptimeRobot y sincronización forzada de huso horario (`TZ`) en los contenedores Linux para estandarización de logs de auditoría.

## 🛠️ Stack Tecnológico
* **Lenguaje:** Python 3.10+
* **Infraestructura:** Render (Bot), Streamlit Cloud (Dashboard), UptimeRobot (Uptime Monitor).
* **Ingesta:** Telegram Bot API (`python-telegram-bot` v20+)
* **Procesamiento (ETL):** `pandas`, `numpy`, `re` (Expresiones Regulares)
* **Visualización:** `streamlit`, `altair`
* **Integración Cloud:** Google Cloud Platform (Google Sheets API, `gspread`)

## 🚀 Guía de Uso Rápido
1. **Ingesta:** Usa el comando `/rutina` en Telegram para recibir tu Briefing Táctico y presiona **Iniciar**.
2. **Ejecución Continua:** El bot te pedirá el registro (`Reps, Peso, Calentamiento, Obs`). Al enviarlo, el sistema saltará automáticamente al siguiente ejercicio de tu planificación.
3. **Visualización:** Accede a la URL en Streamlit Cloud para auditar el cumplimiento del bloque, la recuperación del SNC y visualizar los gráficos de meta vs realidad.