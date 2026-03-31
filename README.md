# Gym Tracker Data Pipeline 🏋️‍♂️📊

Pipeline de ingesta de datos en tiempo real diseñado para capturar, transformar y almacenar métricas de entrenamiento físico desde una interfaz móvil interactiva (Telegram) hacia un Data Warehouse operativo (Google Sheets), preparándolo para visualización en Business Intelligence.

## 🎯 El Problema de Negocio
El registro manual de entrenamientos en aplicaciones de notas convencionales genera silos de datos, pérdida de información por scroll y requiere un retrabajo manual (Data Entry) propenso a errores para consolidar la información en hojas de cálculo para su análisis a largo plazo. 

Además, registrar datos textualmente en un smartphone durante un entrenamiento físico de alta intensidad genera una alta carga cognitiva y errores tipográficos frecuentes.

## 💡 La Solución (V2 - Arquitectura Interactiva)
Se construyó un bot en Telegram respaldado por un motor asíncrono en Python. A diferencia de un bot de comandos tradicional, el sistema implementa un **Flujo Conversacional (State Machine)** que lee la planificación dinámica desde la base de datos y despliega **botones interactivos (Inline Keyboards)**. Esto reduce la fricción del usuario a cero, permitiendo registrar la hipertrofia (Peso, Reps, Notas) con clics en lugar de tipeo complejo, y escribiendo mediante lógica UPSERT en la capa transaccional.

## 🏗️ Arquitectura de Alto Nivel

[Usuario / Telegram Web] 
       | (JSON API / Webhooks)
       v
[Python Script (State Machine)] ---> Despliegue de UI Dinámica (Botones)
       |                             Parsea variables (Reps, Peso, Obs)
       | (Google OAuth2 / gspread)   Manejo de I/O Asíncrono (async/await)
       v
[Google Sheets] ---> Lectura (SELECT metas) y Escritura (UPSERT datos reales)

## 🧠 Características Técnicas Destacadas
* **Máquina de Estados (ConversationHandler):** Control estricto de la interacción del usuario (Selección -> Ingreso de Datos -> Confirmación), evitando inyecciones de datos erróneos.
* **Acceso a Datos O(1):** En lugar de iterar bases de datos para buscar ejercicios, los botones generados mapean dinámicamente el `index` de la fila de la hoja de cálculo (`callback_data`), logrando lecturas y escrituras directas y eficientes.
* **Lógica UPSERT Segura:** El código lee el estado actual de la celda de observaciones antes de escribir, concatenando los nuevos registros de peso y sensaciones sin destruir la planificación histórica ("Cierre Q1").

## 🛠️ Stack Tecnológico
* **Lenguaje:** Python 3.10+
* **Interfaces:** Telegram Bot API (`python-telegram-bot` v20+)
* **Integración Cloud:** Google Cloud Platform (Google Sheets API, IAM Service Accounts, `gspread`)
* **Seguridad:** Manejo de variables de entorno (`python-dotenv`) para proteger tokens.

## 🚀 Guía de Uso Rápido
El bot guía al usuario paso a paso sin necesidad de memorizar formatos complejos:

1. **Comando inicial:** `/rutina`
2. **Respuesta del Bot:** Despliega el resumen de los ejercicios planificados para la fecha de hoy (`datetime.now()`) con botones interactivos.
3. **Acción:** El usuario hace clic en un ejercicio (Ej: *Press con Mancuernas Plano*).
4. **Ingreso:** El bot solicita las variables. El usuario responde con un CSV simple: `12, 30, 2 series, cierre Q1 buena contracción`.
5. **Carga:** El sistema localiza las coordenadas exactas y actualiza las celdas específicas en tiempo real.