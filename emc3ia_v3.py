import os, json, requests, subprocess, time, re, threading, queue
from flask import Flask, request, send_from_directory
from twilio.rest import Client
from gtts import gTTS

GEMINI_KEY   = os.getenv("API_KEY")
PEXELS_KEY   = os.getenv("PEXELS_KEY")
ELEVEN_KEY   = os.getenv("ELEVEN_KEY")
TWILIO_SID   = "ACccd1476dfbe83ea18954cb2049281efe"
TWILIO_TOKEN = "a797ddb3f21a7c85556b2a3cca4f1d66"
TWILIO_NUM   = "whatsapp:+14155238886"
URL_PUBLICA  = os.getenv("TUNNEL_URL", "https://c8055c42a346ba.lhr.life")

PASTA = "/sdcard/EMC3_IA"
for d in ["videos", "cortes", "audio", "legendas", "textos"]:
    os.makedirs(f"{PASTA}/{d}", exist_ok=True)

app = Flask(__name__)
twilio = Client(TWILIO_SID, TWILIO_TOKEN)

class GerenciadorTarefas:
    def __init__(self):
        self.fila = queue.Queue()
        self.tarefa_atual = None
        self.cancelar_flag = False
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._processar, daemon=True)
        self.worker.start()

    def adicionar(self, nome, func, args=()):
        item = {"nome": nome, "func": func, "args": args}
        self.fila.put(item)
        return self.fila.qsize()

    def cancelar(self):
        with self.lock:
            self.cancelar_flag = True
            while not self.fila.empty():
                try:
                    self.fila.get_nowait()
                except:
                    pass
        return True

    def status(self):
        with self.lock:
            return self.tarefa_atual, self.fila.qsize()

    def _processar(self):
        while True:
            try:
                item = self.fila.get(timeout=1)
                with self.lock:
                    self.tarefa_atual = item["nome"]
                    self.cancelar_flag = False
                try:
                    item["func"](*item["args"])
                except Exception as e:
                    print(f"[Erro] {e}")
                finally:
                    with self.lock:
                        self.tarefa_atual = None
                self.fila.task_done()
            except queue.Empty:
                continue

gerenciador = GerenciadorTarefas()
