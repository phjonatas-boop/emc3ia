import os
import json
import re
import time
import queue
import threading
import subprocess
import requests
from flask import Flask, request, send_from_directory
from twilio.rest import Client
from gtts import gTTS

GEMINI_KEY   = os.getenv("API_KEY", "")
PEXELS_KEY   = os.getenv("PEXELS_KEY", "")
ELEVEN_KEY   = os.getenv("ELEVEN_KEY", "")
TWILIO_SID   = "ACccd1476dfbe83ea18954cb2049281efe"
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "e12aa8ef4be9a367e1a173a5599d4353")
TWILIO_NUM   = "whatsapp:+14155238886"
TUNNEL_URL   = os.getenv("TUNNEL_URL", "")
PORT         = int(os.getenv("PORT", "5001"))

HOME  = os.path.expanduser("~")
PASTA = os.path.join(HOME, "EMC3_IA")
for d in ["videos", "cortes", "audio", "textos", "legendas"]:
    os.makedirs(os.path.join(PASTA, d), exist_ok=True)

app    = Flask(__name__)
twilio = Client(TWILIO_SID, TWILIO_TOKEN)


class Fila:
    def __init__(self):
        self.q     = queue.Queue()
        self.atual = None
        self.parar = False
        self.lock  = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def add(self, nome, fn, args=()):
        self.q.put((nome, fn, args))
        return self.q.qsize()

    def cancelar(self):
        with self.lock:
            self.parar = True
            while not self.q.empty():
                try: self.q.get_nowait()
                except: pass

    def status(self):
        with self.lock:
            return self.atual, self.q.qsize()

    def cancelado(self):
        return self.parar

    def _loop(self):
        while True:
            try:
                nome, fn, args = self.q.get(timeout=1)
                with self.lock:
                    self.atual = nome
                    self.parar = False
                try:
                    fn(*args)
                except Exception as e:
                    print(f"[ERRO] {e}")
                finally:
                    with self.lock:
                        self.atual = None
                self.q.task_done()
            except queue.Empty:
                continue


fila = Fila()


def enviar(para, texto):
    try:
        twilio.messages.create(
            body=str(texto)[:1500],
            from_=TWILIO_NUM,
            to=f"whatsapp:{para}"
        )
    except Exception as e:
        print(f"[ERRO ENVIAR] {e}")


def enviar_arquivo(para, caminho, legenda=""):
    try:
        nome = os.path.basename(caminho)
        url  = f"{TUNNEL_URL}/arquivo/{nome}"
        twilio.messages.create(
            media_url=[url],
            body=str(legenda)[:1500],
            from_=TWILIO_NUM,
            to=f"whatsapp:{para}"
        )
    except Exception as e:
        print(f"[ERRO MIDIA] {e}")
        enviar(para, f"Arquivo salvo em: {caminho}")


@app.route("/arquivo/<nome>")
def servir(nome):
    for sub in ["videos", "cortes", "audio", "textos"]:
        p = os.path.join(PASTA, sub, nome)
        if os.path.exists(p):
            return send_from_directory(os.path.join(PASTA, sub), nome)
    return "nao encontrado", 404


def gemini(prompt, system=""):
    url  = (
        "https://generativelanguage.googleapis.com/v1beta"
        f"/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    )
    txt  = f"[INSTRUCAO]: {system}\n\n{prompt}" if system else prompt
    data = {"contents": [{"parts": [{"text": txt}]}]}
    try:
        r = requests.post(url, json=data, timeout=25).json()
        return r["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"[Erro: {e}]"


def sh(c):
    os.system(c + " 2>/dev/null")


def duracao(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except:
        return 30.0


def gerar_voz(texto, saida):
    try:
        h = {"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"}
        b = {
            "text": texto,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.65, "similarity_boost": 0.82}
        }
        r = requests.post(
            "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM",
            headers=h, json=b, timeout=30
        )
        if r.status_code == 200:
            with open(saida, "wb") as f:
                f.write(r.content)
            return
    except Exception as e:
        print(f"[ElevenLabs falhou] {e}")
    gTTS(texto[:500], lang="pt").save(saida)


def baixar_pexels(temas, qtd):
    headers = {"Authorization": PEXELS_KEY}
    videos  = []
    for i, tema in enumerate(temas[:qtd]):
        if fila.cancelado():
            break
        saida = os.path.join(PASTA, f"bg_{i:02d}.mp4")
        if os.path.exists(saida) and os.path.getsize(saida) > 100000:
            videos.append(saida)
            continue
        try:
            url = f"https://api.pexels.com/videos/search?query={tema}&per_page=3&orientation=portrait"
            res = requests.get(url, headers=headers, timeout=10).json()
            baixou = False
            for v in res.get("videos", []):
                arqs = sorted(v.get("video_files", []),
                              key=lambda x: x.get("width", 0), reverse=True)
                for arq in arqs:
                    if arq.get("width", 0) >= 720:
                        r = os.system(f'wget -q --timeout=20 -O "{saida}" "{arq["link"]}"')
                        if r == 0 and os.path.getsize(saida) > 100000:
                            baixou = True
                            break
                if baixou:
                    break
            if not baixou:
                fundo_preto(saida, i)
        except:
            fundo_preto(saida, i)
        videos.append(saida)
        time.sleep(0.3)
    return videos


def fundo_preto(saida, idx):
    cores = ["0x0a0a2e", "0x1a0a2e", "0x0a2e1a", "0x2e0a0a", "0x0e0e0e"]
    cor   = cores[idx % len(cores)]
    sh(f'ffmpeg -y -f lavfi -i "color=c={cor}:size=1080x1920:rate=30" -t 10 "{saida}"')


def musica_fundo():
    arq = os.path.join(PASTA, "audio", "musica.mp3")
    if os.path.exists(arq) and os.path.getsize(arq) > 50000:
        return arq
    url = "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Chad_Crouch/Arps/Chad_Crouch_-_Shipping_Lanes.mp3"
    os.system(f'wget -q --timeout=30 -O "{arq}" "{url}"')
    if not os.path.exists(arq) or os.path.getsize(arq) < 50000:
        sh(f'ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 120 "{arq}"')
    return arq


def texto_viral(tema, frases=None):
    ctx    = ""
    if frases:
        ctx = "Frases do video:\n" + "\n".join(frases[:5])
    prompt = (
        f"Crie texto viral para TikTok sobre: {tema}\n{ctx}\n"
        "3 paragrafos curtos e impactantes.\n"
        "Linguagem jovem. Pergunta no final.\n"
        "20 hashtags virais em portugues e ingles.\n\n"
        "Formato:\n[TEXTO]\n...\n[HASHTAGS]\n#tag1 #tag2 ..."
    )
    resultado = gemini(prompt)
    nome = re.sub(r'[^a-zA-Z0-9]', '_', tema)[:20]
    arq  = os.path.join(PASTA, "textos", f"EMC3_{nome}.txt")
    with open(arq, "w", encoding="utf-8") as f:
        f.write(resultado)
< truncated lines 231-420 >
            f"drawtext=text='{fs}':"
            f"fontcolor=white:fontsize=70:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"box=1:boxcolor=black@0.65:boxborderw=22:"
            f"alpha='if(lt(t,{fade}),t/{fade},"
            f"if(gt(t,{dur_frase-fade}),({dur_frase}-t)/{fade},1))',"
            f"drawtext=text='EMC\u00b3 IA':"
            f"fontcolor=white@0.7:fontsize=36:"
            f"x=(w-text_w)/2:y=55:"
            f"box=1:boxcolor=black@0.4:boxborderw=10"
        )
        sh(
            f'ffmpeg -y -stream_loop 5 -i "{bg}" -t {dur_frase:.2f} '
            f'-vf "{filtro}" '
            f'-c:v libx264 -preset ultrafast -crf 22 '
            f'-an -r 30 -pix_fmt yuv420p "{saida}"'
        )
        if os.path.exists(saida):
            clipes.append(saida)
    lista     = os.path.join(PASTA, "lista.txt")
    sem_audio = os.path.join(PASTA, "sem_audio.mp4")
    with open(lista, "w") as f:
        for c in clipes:
            f.write(f"file '{c}'\n")
    sh(f'ffmpeg -y -f concat -safe 0 -i "{lista}" -c copy "{sem_audio}"')
    musica = musica_fundo()
    nome   = re.sub(r'[^a-zA-Z0-9]', '_', tema)[:20]
    final  = os.path.join(PASTA, "videos", f"EMC3_{nome}.mp4")
    sh(
        f'ffmpeg -y -i "{sem_audio}" -i "{arq_voz}" -i "{musica}" '
        f'-filter_complex "[1:a]volume=1.8[voz];[2:a]volume=0.2[bg];[voz][bg]amix=inputs=2[audio]" '
        f'-map 0:v -map "[audio]" '
        f'-c:v copy -c:a aac -b:a 192k -shortest '
        f'-movflags +faststart "{final}"'
    )
    for c in clipes:
        if os.path.exists(c): os.remove(c)
    for f in [lista, sem_audio]:
        if os.path.exists(f): os.remove(f)
    if os.path.exists(final):
        mb  = os.path.getsize(final) // (1024 * 1024)
        sh(f'termux-media-scan "{final}"')
        txt = texto_viral(tema, frases)
        enviar_arquivo(para, final,
            f"Video pronto! ({mb}MB)\n\nTexto para postar:\n{txt[:800]}")
    else:
        enviar(para, "Erro ao gerar video.")


def _cortes_task(url_yt, num, para):
    if fila.cancelado():
        enviar(para, "Tarefa cancelada.")
        return
    arq_yt = os.path.join(PASTA, "yt.mp4")
    ret    = os.system(
        f'yt-dlp -f "best[height<=720]" -o "{arq_yt}" "{url_yt}" 2>/dev/null'
    )
    if ret != 0 or not os.path.exists(arq_yt):
        enviar(para, "Nao consegui baixar. Verifique o link.")
        return
    dur    = duracao(arq_yt)
    titulo = gemini(f"Sugira tema em 3 palavras para video de {dur:.0f}s.")
    enviar(para, f"Video baixado ({dur:.0f}s). Gerando {num} cortes...")
    analise = gemini(
        f"Video de {dur:.0f}s. Sugira {num} cortes virais de 30-45s. "
        "Formato: INICIO-FIM em segundos. Ex: 45-90. Um por linha."
    )
    cortes = []
    for linha in analise.split("\n"):
        m = re.search(r'(\d+)\s*[-]\s*(\d+)', linha)
        if m:
            ini, fim = int(m.group(1)), int(m.group(2))
            if fim > ini and fim <= dur and (fim - ini) <= 60:
                cortes.append((ini, fim))
    if not cortes:
        iv     = int(dur / num)
        cortes = [(i*iv, min(i*iv+40, dur)) for i in range(num)]
    for i, (ini, fim) in enumerate(cortes[:num]):
        if fila.cancelado():
            enviar(para, f"Cancelado! {i} cortes salvos.")
            return
        saida = os.path.join(PASTA, "cortes", f"EMC3_corte_{i+1:02d}.mp4")
        sh(
            f'ffmpeg -y -ss {ini} -i "{arq_yt}" -t {fim-ini} '
            f'-vf "scale=1080:1920:force_original_aspect_ratio=increase,'
            f'crop=1080:1920,setsar=1,'
            f'drawtext=text=\'EMC\u00b3 IA\':'
            f'fontcolor=white@0.8:fontsize=40:'
            f'x=(w-text_w)/2:y=60:'
            f'box=1:boxcolor=black@0.5:boxborderw=12" '
            f'-c:v libx264 -preset ultrafast -crf 22 '
            f'-c:a aac -b:a 128k "{saida}"'
        )
        if os.path.exists(saida):
            sh(f'termux-media-scan "{saida}"')
            txt = texto_viral(f"corte {i+1} - {titulo}")
            enviar_arquivo(para, saida, f"Corte {i+1}/{num}\n\n{txt[:600]}")
            time.sleep(2)
    enviar(para, f"{len(cortes)} cortes prontos na galeria!")


@app.route("/webhook", methods=["POST"])
def webhook():
    de    = request.form.get("From", "").replace("whatsapp:", "")
    corpo = request.form.get("Body", "").strip()
    tipo  = request.form.get("MediaContentType0", "")
    url_m = request.form.get("MediaUrl0", "")
    n_mid = int(request.form.get("NumMedia", 0))
    print(f"[{de}]: {corpo} | midia={n_mid} tipo={tipo}")
    threading.Thread(target=processar, args=(de, corpo, tipo, url_m, n_mid)).start()
    return "", 200


def processar(de, corpo, tipo, url_m, n_mid):
    c = corpo.lower().strip()

    if n_mid > 0 and "audio" in tipo:
        enviar(de, "Transcrevendo seu audio...")
        texto = transcrever_audio(url_m)
        if texto:
            enviar(de, f"Entendi: {texto}\nProcessando...")
            processar(de, texto, "", "", 0)
        else:
            enviar(de, "Nao entendi o audio. Tente falar mais devagar ou digitar!")
        return

    if any(p in c for p in ["cancelar", "cancela", "parar", "stop"]):
        fila.cancelar()
        enviar(de, "Tarefa cancelada! Fila limpa.")
        return

    if any(p in c for p in ["status", "fila", "andamento"]):
        atual, qtd = fila.status()
        if atual:
            enviar(de, f"Executando: {atual}\nNa fila: {qtd}\nDigite cancelar para parar.")
        else:
            enviar(de, "EMC3 IA livre!")
        return

    if any(p in c for p in ["bateria", "carga"]):
        ver_bateria(de)
        return

    if "lanterna" in c:
        lanterna(c, de)
        return

    if "volume" in c and any(p in c for p in ["aumenta", "diminui", "sobe", "baixa", "mudo"]):
        controlar_volume(c, de)
        return

    if any(p in c for p in ["localizacao", "onde estou", "gps"]):
        ver_localizacao(de)
        return

    if any(p in c for p in ["foto", "selfie", "camera"]):
        tirar_foto(de)
        return

    if any(p in c for p in ["abre ", "abrir ", "abra "]):
        nome = gemini(f"Qual app o usuario quer abrir: {corpo}. Responda apenas o nome do app.")
        abrir_app(nome.strip(), de)
        return

    if any(p in c for p in ["alarme", "acorda", "lembrete"]):
        criar_alarme(c, de)
        return

    if "youtube.com" in c or "youtu.be" in c:
        m = re.search(r'https?://\S+', corpo)
        if m:
            n  = 5
            mn = re.search(r'(\d+)\s*cortes?', c)
            if mn: n = min(int(mn.group(1)), 10)
            enviar(de, f"Cortes enfileirados! {n} cortes.")
            fila.add(f"Cortes ({n})", _cortes_task, (m.group(), n, de))
        return

    if any(p in c for p in ["oi", "ola", "menu", "ajuda", "help", "emc", "inicio"]):
        enviar(de,
            "EMC3 IA v5.0\n\n"
            "VIDEO:\ncria video sobre [tema]\n\n"
            "CORTES:\nCole link do YouTube\n\n"
            "TEXTO:\ntexto viral sobre [tema]\n\n"
            "CELULAR:\nabre whatsapp\nabre tiktok\n"
            "bateria\nliga lanterna\ndesliga lanterna\n"
            "aumenta volume\ndiminui volume\n"
            "minha localizacao\ntira foto\n"
            "alarme as 7:30\n\n"
            "CONTROLE:\nstatus\ncancelar"
        )
        return

    if any(p in c for p in ["video", "cria", "gera", "viral", "reels", "shorts"]):
        tema   = gemini(f"Extraia o tema em 3-5 palavras: {corpo}")
        estilo = "motivacional"
        if any(p in c for p in ["espirit", "neville", "universo"]):
            estilo = "espiritual"
        elif any(p in c for p in ["educa", "dica", "como"]):
            estilo = "educativo"
        elif any(p in c for p in ["humor", "engraca"]):
            estilo = "humor"
        formato = "quadrado" if "quadrad" in c else "vertical"
        enviar(de, f"Video enfileirado!\nTema: {tema}\nEstilo: {estilo}")
        fila.add(f"Video: {tema}", _video_task, (tema.strip(), formato, estilo, de))
        return

    if any(p in c for p in ["texto", "hashtag", "caption"]):
        tema = gemini(f"Extraia o tema em 3-5 palavras: {corpo}")
        enviar(de, "Gerando texto viral...")
        txt = texto_viral(tema.strip())
        enviar(de, f"Texto pronto:\n\n{txt[:1400]}")
        return

    resp = gemini(corpo,
        system=(
            "Voce e EMC3 IA, assistente viral brasileiro. "
            "Responda em portugues, curto e animado."
        )
    )
    enviar(de, resp[:1500])


if __name__ == "__main__":
    print("EMC3 IA v5.0 pronto!")
    print(f"Pasta: {PASTA}")
    print(f"URL:   {TUNNEL_URL}")
    print(f"Porta: {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
