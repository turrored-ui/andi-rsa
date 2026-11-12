import re
import csv
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

BASE = Path(__file__).parent
LOG_FILE = BASE / "preguntas_sin_respuesta.csv"
LOCK = threading.Lock()
TAG = re.compile(r"\[\[REGISTRAR:\s*(.*?)\]\]", re.S)

FALLBACK = (
    "Ahora mismo no puedo responder. Puede hablar con un asesor: call center "
    "(601) 555 0100 o WhatsApp +57 300 555 0100 (L-V 7:00-19:00, sáb 8:00-14:00)."
)

st.set_page_config(page_title="Asistente virtual Red Salud Andina", page_icon="💬")


@st.cache_resource
def cargar():
    system = (
        (BASE / "prompt_sistema.md").read_text(encoding="utf-8")
        + "\n\n"
        + (BASE / "base_conocimiento.md").read_text(encoding="utf-8")
    )
    # La clave va en Settings > Secrets de Streamlit Cloud. Nunca en el código.
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    modelo = st.secrets.get("MODEL_NAME", "gemini-2.5-flash")
    return client, system, modelo


def limpiar(texto: str) -> str:
    """Quita números largos y correos por si se cuelan datos personales."""
    texto = re.sub(r"\d{5,}", "[número]", texto)
    texto = re.sub(r"\S+@\S+", "[correo]", texto)
    return texto.strip()[:200]


def registrar(pregunta: str) -> None:
    with LOCK:
        nuevo = not LOG_FILE.exists()
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["fecha", "pregunta_sin_respuesta"])
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), limpiar(pregunta)])


def responder(mensaje: str, historial: list) -> str:
    client, system, modelo = cargar()
    contents = []
    for m in historial[-12:]:
        rol = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=rol, parts=[types.Part(text=m["content"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=mensaje[:600])]))
    try:
        resp = client.models.generate_content(
            model=modelo,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system, temperature=0.2, max_output_tokens=600
            ),
        )
        texto = resp.text or ""
    except Exception as e:
        print("Error del modelo:", e)
        return FALLBACK
    for q in TAG.findall(texto):
        registrar(q)
    return TAG.sub("", texto).strip() or FALLBACK


st.title("Asistente virtual de Red Salud Andina")
st.caption(
    "Resuelve dudas básicas (horarios, requisitos, cuotas, resultados). "
    "No agenda citas, no ve datos de pacientes ni da consejo médico. "
    "Por favor no escriba datos personales."
)

tab_chat, tab_log = st.tabs(["Chat", "Preguntas sin respuesta (operación)"])

with tab_chat:
    if "mensajes" not in st.session_state:
        st.session_state.mensajes = [
            {
                "role": "assistant",
                "content": "Hola, soy el asistente virtual de Red Salud Andina. ¿En qué le puedo ayudar?",
            }
        ]
    for m in st.session_state.mensajes:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    pregunta = st.chat_input("Escriba su pregunta")
    if pregunta:
        historial = list(st.session_state.mensajes)
        st.session_state.mensajes.append({"role": "user", "content": pregunta})
        with st.chat_message("user"):
            st.markdown(pregunta)
        with st.chat_message("assistant"):
            with st.spinner("Escribiendo..."):
                respuesta = responder(pregunta, historial)
            st.markdown(respuesta)
        st.session_state.mensajes.append({"role": "assistant", "content": respuesta})

with tab_log:
    st.write("Lista que la operación revisa cada lunes. Solo guarda el texto de la pregunta.")
    if st.button("Actualizar"):
        st.rerun()
    if LOG_FILE.exists():
        st.dataframe(pd.read_csv(LOG_FILE), use_container_width=True)
    else:
        st.info("Todavía no hay preguntas registradas.")
