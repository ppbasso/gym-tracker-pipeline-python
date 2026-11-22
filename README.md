# Gym & Health Data Pipeline 🏋️‍♂️📊

Pipeline de ingesta, procesamiento y auditoría de datos en tiempo real diseñado para capturar métricas de **entrenamiento de fuerza, nutrición, biometría corporal y gasto energético (NEAT)** desde una interfaz móvil interactiva en **Telegram**, almacenarlas en un Data Warehouse operativo en **Google Sheets** y auditarlas mediante un Dashboard de Business Intelligence multivista en **Streamlit**.

## 🎯 El Problema de Negocio
El registro manual de entrenamientos, comidas y métricas corporales en aplicaciones de notas convencionales genera silos de datos, pérdida de contexto histórico y requiere un retrabajo manual (*Data Entry*) propenso a errores para consolidar la información en hojas de cálculo.

Además, ingresar datos textualmente en un smartphone durante sesiones de alta intensidad física genera alta carga cognitiva, fricción operativa y errores tipográficos frecuentes.

## 💡 La Solución (V2 - Ecosistema Interactivo en Telegram + IA)
Se construyó un bot en Telegram respaldado por un motor asíncrono en Python (`bot.py`) alojado en **Render**, operando mediante *Long Polling* y protegido por una capa de autenticación por ID (`@requiere_admin`). El sistema integra cuatro módulos operativos:

1. **Entrenamiento Heavy Duty / Doble Progresión (`/rutina` y `/posponer`):** Implementa máquinas de estados (`ConversationHandler`) con lógica de **Linear Stepper (Auto-avance)**, cronómetro táctico de sesión y **Radar *Up Next***. Soporta registro de 1 o 2 series efectivas (`S1` y `S2`, ej. `8-8`) mediante *Update No Destructivo (Append)* y permite reagendar sesiones completas con cálculo automático de fechas (`/posponer`).
2. **Nutrición Soberana con IA (`/comer`, `/cola`, `/sync`):** Conecta con **Google Gemini (`google-genai`)** anclado a la Tabla de Composición Química de Alimentos Chilenos del **INTA** para transformar descripciones en lenguaje natural en macros estructurados. Incluye válvula de memoria (`asyncio.Lock`), escudo offline ante caídas de API (`503`) y un trabajador autónomo en segundo plano (**Sabueso de Nutrición**) con *backoff* anti-`429`.
3. **Biometría Corporal (`/peso` y `/medidas`):** Captura rápida de peso diario (rellenando métricas secundarias con `0`) y registro quincenal de 9 perímetros corporales mediante inyección quirúrgica de filas.
4. **Metabolismo y NEAT (`/pasos`):** Motor **UPSERT** (*Update or Insert*) que actualiza o crea registros diarios de pasos (soportando registro retroactivo con `"ayer"`).

Para garantizar disponibilidad 24/7 en la capa gratuita de Render, el bot levanta un micro-servidor HTTP (`keep_alive.py`) monitoreado externamente por **UptimeRobot**, junto con un planificador de tareas (`JobQueue`) para alarmas matutinas asimétricas y recordatorios pre-entreno.

> *Visualización Ingesta de Datos*
<br>
<img src="bot_demo.gif" width="300" alt="Bot Telegram Demo">

## 📊 La Solución (V3 - Capa de Auditoría y BI Multivista / Streamlit)
Para cerrar el ciclo de vida del dato, se desarrolló un Dashboard Analítico (`dashboard.py`) en **Streamlit Cloud** con arquitectura modular en `views/`:
* `views/1_hipertrofia.py`: Auditoría de rendimiento físico, limpieza avanzada vía Regex, estandarización de ejercicios (MDM), cálculo de **E1RM** (1 Repetición Máxima Estimada), cruce de **Plan (Meta) vs. Realidad (Ejecución)** y control de fatiga del Sistema Nervioso Central (SNC).
* `views/2_nutricion.py`: Seguimiento de ingesta calórica, distribución de macronutrientes y adherencia nutricional.
* `views/3_metabolismo.py`: Evolución de peso corporal, biometría y gasto energético por actividad diaria (NEAT).

> *Visualización Dashboard Auditoría*
<br>
<img src="dashboard_demo.gif" width="300" alt="Dashboard BI Demo">

## 🏗️ Arquitectura de Alto Nivel

~~~text
[Usuario / Telegram Mobile]
       | (Long Polling API + Modo Fantasma)
       v
[Render Cloud (Python Bot + Keep-Alive)] <---> [UptimeRobot (Monitor HTTP)]
       |                         |
       | (JSON / Prompts INTA)   | (Google OAuth2 / gspread)
       v                         v
[Google Gemini AI]      [Google Sheets (Data Warehouse)]
                         ├── TESTbot      (Planificación y Series S1/S2)
                         ├── Nutricion    (Calorías y Macros INTA)
                         ├── Mediciones   (Peso y Biometría 9 puntos)
                         └── Metabolismo  (Pasos Diarios / NEAT)
                                 |
                                 | (Pandas / Regex ETL)
                                 v
                  [Streamlit Cloud Dashboard (views/)]
                   ├── 1_hipertrofia.py
                   ├── 2_nutricion.py
                   └── 3_metabolismo.py
~~~

## 🧠 Características Técnicas Destacadas
* **Motor Forense (Contexto Histórico):** Algoritmo de retroceso temporal que escanea el Data Warehouse para inyectar la última marca válida (*Reps x Peso real* extraído vía Regex) directamente en la UI del bot, descartando heurísticamente semanas de descarga para proteger la sobrecarga progresiva.
* **Soporte de Doble Progresión (`S1` y `S2`) y Update No Destructivo:** Parsea repeticiones simples (`8`) o dobles (`8-8`) separando cada serie en su columna correspondiente (`E` y `F`), mientras concatena calentamiento, peso real y observaciones en la columna de notas sin sobrescribir el historial previo.
* **Modo Fantasma (Zero-Clutter UX):** Elimina automáticamente los mensajes enviados por el usuario y edita en tiempo real una única burbuja maestra durante toda la sesión de entrenamiento.
* **Resiliencia IA & Tolerancia a Fallos (`Anti-503 / Anti-429`):** Si la API de Gemini falla o alcanza límite de cuota, el bot encola el registro en Google Sheets (`⏳ Pendiente IA`) y lo resuelve automáticamente en segundo plano mediante el **Sabueso de Nutrición** o bajo demanda con `/sync`.
* **Sincronización Horaria Inmune a DST:** Uso nativo de `zoneinfo` (`America/Santiago`) en lugar de offsets fijos o variables de entorno del contenedor, evitando desfases en alarmas y registros ante cambios de horario de verano/invierno.
* **Motor de Renderizado Dual (BI):** Análisis bifurcado en Streamlit bajo un eje **Biomecánico** (grupos musculares aislados) o un eje **Operativo** basado en rutinas deterministas (*Módulo Alpha / Módulo Omega*), agnóstico a los días de la semana.

## 🛠️ Stack Tecnológico
* **Lenguaje:** Python 3.10+
* **Infraestructura:** Render (Bot + Keep-Alive), Streamlit Cloud (Dashboard), UptimeRobot (Monitoreo 24/7).
* **Ingesta y Automatización:** `python-telegram-bot` v20+ (`ConversationHandler` + `JobQueue`), `asyncio`.
* **Inteligencia Artificial:** `google-genai` (Gemini).
* **Procesamiento (ETL) y Datos:** `pandas`, `numpy`, `re` (Expresiones Regulares), `zoneinfo`.
* **Visualización:** `streamlit`, `altair`.
* **Integración Cloud y Seguridad:** Google Sheets API (`gspread`, `google-auth`), `python-dotenv`.

## 🚀 Guía de Uso Rápido
1. **Entrenamiento (`/rutina`):** Inicia la sesión del día y presiona **Iniciar**. Envía cada ejercicio en el formato `Calentamiento, Peso, Reps, Obs` (ej. `1x15 16kg, 26, 8-8, ok`). El bot guardará `S1` y `S2` y avanzará automáticamente al siguiente ejercicio.
2. **Reagendamiento (`/posponer`):** Traslada una sesión pendiente a otra fecha (`+1 día`, `+2 días`, `Próximo Lunes` o `Próximo Viernes`) actualizando el Data Warehouse en ráfaga.
3. **Nutrición (`/comer`, `/cola`, `/sync`):** Envía lo que comiste (ej. `/comer 2 hallullas con queso y salami`) para mapear macros vía INTA, audita pendientes con `/cola` o fuerza la sincronización con `/sync`.
4. **Biometría y Pasos (`/peso`, `/medidas`, `/pasos`):** Registra tu peso diario en ayunas, tus 9 perímetros corporales o tus pasos del día/ayer.
5. **Auditoría BI:** Accede al dashboard en Streamlit Cloud para revisar tus curvas de hipertrofia, balance calórico y gasto metabólico.