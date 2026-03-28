#!/usr/bin/env python3
# ╔══════════════════════════════════════════════════════════╗
#  EMC³ IA v3.0 — Agente Viral com WhatsApp
#  Fila inteligente | Cancelar | Status | Simultâneo
# ╚══════════════════════════════════════════════════════════╝

import os, json, requests, subprocess, time, re, threading, queue
from flask import Flask, request, send_from_directory
from twilio.rest import Client
from gtts import gTTS

# ── Chaves ─────────────────────────────────────────────────
GEMINI_KEY   = os.getenv("API_KEY")
PEXELS_KEY   = os.getenv("PEXELS_KEY")
ELEVEN_KEY   = os.getenv("ELEVEN_KEY")
TWILIO_SID   = "ACccd1476dfbe83ea18954cb2049281efe"
TWILIO_TOKEN = "a797ddb3f21a7c85556b2a3cca4f1d66"
TWILIO_NUM   = "whatsapp:+14155238886"
URL_PUBLICA  = os.getenv("TUNNEL_URL", "https://c8055c42a346ba.lhr.life")

# ── Pastas ─────────────────────────────────────────────────
PASTA = "/sdcard/EMC3_IA"
for d in ["videos", "cortes", "audio", "legendas", "textos"]:
    os.makedirs(f"{PASTA}/{d}", exist_ok=True)

# ── Flask + Twilio ─────────────────────────────────────────
app = Flask(__name__)
twilio = Client(TWILIO_SID, TWILIO_TOKEN)

# ══════════════════════════════════════════════════════════
#  SISTEMA DE FILA DE TAREFAS
# ══════════════════════════════════════════════════════════
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
        posicao = self.fila.qsize()
        return posicao

    def cancelar(self):
        with self.lock:
            self.cancelar_flag = True
            # Limpa a fila
            while not self.fila.empty():
                try:
                    self.fila.get_nowait()
                except:
                    pass
        return True

    def status(self):
        with self.lock:
            atual = self.tarefa_atual
            na_fila = self.fila.qsize()
        return atual, na_fila

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
                    print(f"[Erro tarefa] {e}")
                finally:
                    with self.lock:
                        self.tarefa_atual = None
                self.fila.task_done()
            except queue.Empty:
                continue


gerenciador = GerenciadorTarefas()


# ══════════════════════════════════════════════════════════
#  ENVIAR MENSAGEM WHATSAPP
# ══════════════════════════════════════════════════════════
def enviar(para, texto):
    try:
        twilio.messages.create(
            body=texto[:1500],
            from_=TWILIO_NUM,
            to=f"whatsapp:{para}"
        )
    except Exception as e:
        print(f"[Erro enviar] {e}")


def enviar_midia(para, caminho, legenda=""):
    try:
        nome = os.path.basename(caminho)
        url = f"{URL_PUBLICA}/arquivo/{nome}"
        twilio.messages.create(
            media_url=[url],
            body=legenda[:1500],
            from_=TWILIO_NUM,
            to=f"whatsapp:{para}"
        )
    except Exception as e:
        print(f"[Erro mídia] {e}")
        enviar(para, f"✅ Arquivo salvo em: {caminho}")


# ══════════════════════════════════════════════════════════
#  SERVIDOR DE ARQUIVOS
# ══════════════════════════════════════════════════════════
@app.route("/arquivo/<nome>")
def servir_arquivo(nome):
    for sub in ["videos", "cortes", "audio", "textos"]:
        path = f"{PASTA}/{sub}/{nome}"
        if os.path.exists(path):
            return send_from_directory(f"{PASTA}/{sub}", nome)
    return "não encontrado", 404


# ══════════════════════════════════════════════════════════
#  NÚCLEO GEMINI
# ══════════════════════════════════════════════════════════
def gemini(prompt, system=""):
    url = (
        "https://generativelanguage.googleapis.com/v1beta"
        f"/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    )
    texto = f"[INSTRUÇÃO]: {system}\n\n{prompt}" if system else prompt
    data = {"contents": [{"parts": [{"text": texto}]}]}
    try:
        r = requests.post(url, json=data, timeout=25).json()
        return r["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"[Erro: {e}]"


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════
def duracao(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except:
        return 30.0


def cancelado():
    return gerenciador.cancelar_flag


def gerar_voz(texto, saida):
    headers = {"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"}
    body = {
        "text": texto,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.65, "similarity_boost": 0.82}
    }
    res = requests.post(
        "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM",
        headers=headers, json=body, timeout=30
    )
    if res.status_code == 200:
        with open(saida, "wb") as f:
            f.write(res.content)
    else:
        gTTS(texto[:500], lang='pt').save(saida)


def baixar_videos_pexels(temas, qtd):
    headers = {"Authorization": PEXELS_KEY}
    videos = []
    for i, tema in enumerate(temas[:qtd]):
        if cancelado():
            break
        saida = f"{PASTA}/bg_{i:02d}.mp4"
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
                        r = os.system(f'wget -q --timeout=20 -O {saida} "{arq["link"]}"')
                        if r == 0 and os.path.getsize(saida) > 100000:
                            baixou = True
                            break
                if baixou:
                    break
            if not baixou:
                fundo_sintetico(saida, i)
        except:
            fundo_sintetico(saida, i)
        videos.append(saida)
        time.sleep(0.2)
    return videos


def fundo_sintetico(saida, idx):
    cores = ["0x0a0a2e", "0x1a0a2e", "0x0a2e1a", "0x2e0a0a", "0x0e0e0e"]
    cor = cores[idx % len(cores)]
    os.system(
        f"ffmpeg -y -f lavfi -i \"color=c={cor}:size=1080x1920:rate=30\" "
        f"-t 10 {saida} 2>/dev/null"
    )


def baixar_musica():
    arq = f"{PASTA}/audio/musica.mp3"
    if os.path.exists(arq) and os.path.getsize(arq) > 50000:
        return arq
    urls = [
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Chad_Crouch/Arps/Chad_Crouch_-_Shipping_Lanes.mp3",
    ]
    for url in urls:
        ret = os.system(f'wget -q --timeout=20 -O {arq} "{url}"')
        if ret == 0 and os.path.exists(arq) and os.path.getsize(arq) > 50000:
            return arq
    os.system(f"ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 120 {arq} 2>/dev/null")
    return arq


# ══════════════════════════════════════════════════════════
#  TRANSCREVER ÁUDIO DO WHATSAPP
# ══════════════════════════════════════════════════════════
def transcrever_audio(url_midia):
    try:
        arq = f"{PASTA}/audio/wpp_audio.ogg"
        arq_wav = f"{PASTA}/audio/wpp_audio.wav"
        res = requests.get(url_midia, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=20)
        with open(arq, "wb") as f:
            f.write(res.content)
        os.system(f"ffmpeg -y -i {arq} {arq_wav} 2>/dev/null")
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.AudioFile(arq_wav) as source:
            audio = r.record(source)
        return r.recognize_google(audio, language="pt-BR")
    except Exception as e:
        return None


# ══════════════════════════════════════════════════════════
#  GERAR TEXTO VIRAL
# ══════════════════════════════════════════════════════════
def gerar_texto_viral(tema, frases=None):
    contexto = ""
    if frases:
        contexto = "Frases do vídeo:\n" + "\n".join(frases[:5])
    prompt = f"""Crie texto viral para TikTok/Reels sobre: {tema}
{contexto}
- 3 parágrafos curtos e impactantes
- Linguagem jovem
- Pergunta no final para engajamento
- 20 hashtags virais em português e inglês

Formato:
[TEXTO]
...
[HASHTAGS]
#tag1 #tag2 ..."""
    resultado = gemini(prompt)
    nome = tema.replace(" ", "_")[:20]
    arq = f"{PASTA}/textos/EMC3_IA_{nome}.txt"
    with open(arq, "w", encoding="utf-8") as f:
        f.write(resultado)
    return resultado


# ══════════════════════════════════════════════════════════
#  GERAR VÍDEO VIRAL
# ══════════════════════════════════════════════════════════
def _tarefa_video(tema, formato, estilo, para):
    if cancelado():
        enviar(para, "⚠️ Tarefa cancelada antes de iniciar.")
        return

    estilos = {
        "espiritual": "estilo Neville Goddard, espiritual, transcendente",
        "motivacional": "estilo motivacional, energia alta, conquista",
        "educativo": "estilo educativo, informativo, surpreendente",
        "humor": "estilo humorístico, leve, engraçado e viral",
    }
    desc_estilo = estilos.get(estilo, estilos["espiritual"])

    roteiro = gemini(
        f"Crie 8 frases impactantes sobre: {tema}. "
        f"Estilo: {desc_estilo}. Máximo 7 palavras cada. "
        "Retorne SOMENTE as frases, uma por linha."
    )
    frases = [l.strip() for l in roteiro.split("\n")
              if l.strip() and len(l.strip()) > 3][:8]

    if cancelado():
        enviar(para, "⚠️ Tarefa cancelada.")
        return

    arq_voz = f"{PASTA}/audio/voz_viral.mp3"
    gerar_voz(" ... ".join(frases), arq_voz)

    resolucoes = {"vertical": "1080x1920", "quadrado": "1080x1080", "horizontal": "1920x1080"}
    res = resolucoes.get(formato, "1080x1920")
    w, h = res.split("x")

    palavras = gemini(
        f"8 palavras-chave em inglês para vídeos sobre: {tema}. Uma por linha."
    ).split("\n")[:8]

    if cancelado():
        enviar(para, "⚠️ Tarefa cancelada.")
        return

    videos_bg = baixar_videos_pexels(palavras, len(frases))
    dur_total = duracao(arq_voz)
    tempos = [max(dur_total / len(frases), 2.5)] * len(frases)

    clipes = []
    for i, (frase, bg, dur_c) in enumerate(zip(frases, videos_bg, tempos)):
        if cancelado():
            enviar(para, "⚠️ Tarefa cancelada durante a montagem.")
            return

        saida = f"{PASTA}/clipe_{i:02d}.mp4"
        frase_safe = (frase.replace("'", "\u2019")
                          .replace(":", "\\:")
                          .replace("%", "\\%")
                          .replace('"', ""))
        fade = 0.3
        filtro = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,"
            f"colorchannelmixer=rr=0.5:gg=0.5:bb=0.5,"
            f"drawtext=text='{frase_safe}':"
            f"fontcolor=white:fontsize=72:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"box=1:boxcolor=black@0.65:boxborderw=24:"
            f"alpha='if(lt(t,{fade}),t/{fade},if(gt(t,{dur_c-fade}),({dur_c}-t)/{fade},1))',"
            f"drawtext=text='EMC\u00b3 IA':"
            f"fontcolor=white@0.7:fontsize=38:"
            f"x=(w-text_w)/2:y=60:"
            f"box=1:boxcolor=black@0.4:boxborderw=10"
        )
        os.system(
            f"ffmpeg -y -stream_loop 5 -i {bg} -t {dur_c:.2f} "
            f"-vf \"{filtro}\" "
            f"-c:v libx264 -preset ultrafast -crf 22 "
            f"-an -r 30 -pix_fmt yuv420p {saida} 2>/dev/null"
        )
        if os.path.exists(saida):
            clipes.append(saida)

    lista = f"{PASTA}/lista.txt"
    with open(lista, "w") as f:
        for c in clipes:
            f.write(f"file '{c}'\n")

    sem_audio = f"{PASTA}/sem_audio.mp4"
    os.system(f"ffmpeg -y -f concat -safe 0 -i {lista} -c copy {sem_audio} 2>/dev/null")

    musica = baixar_musica()
    nome = tema.replace(" ", "_")[:20]
    final = f"{PASTA}/videos/EMC3_IA_{nome}.mp4"

    os.system(
        f"ffmpeg -y -i {sem_audio} -i {arq_voz} -i {musica} "
        f"-filter_complex \"[1:a]volume=1.8[voz];[2:a]volume=0.2[bg];"
        f"[voz][bg]amix=inputs=2[audio]\" "
        f"-map 0:v -map \"[audio]\" "
        f"-c:v copy -c:a aac -b:a 192k -shortest "
        f"-movflags +faststart {final} 2>/dev/null"
    )

    for c in clipes:
        if os.path.exists(c): os.remove(c)
    for f in [lista, sem_audio]:
        if os.path.exists(f): os.remove(f)

    if os.path.exists(final):
        mb = os.path.getsize(final) // (1024*1024)
        os.system(f"termux-media-scan {final} 2>/dev/null")
        texto_viral = gerar_texto_viral(tema, frases)
        enviar_midia(para, final,
            f"✅ *Vídeo pronto!* ({mb}MB)\n\n📝 *Texto para postar:*\n{texto_viral[:800]}")
    else:
        enviar(para, "❌ Erro ao gerar vídeo. Tente novamente.")


def gerar_video_viral(tema, formato, estilo, para):
    enviar(para, f"🎬 *Vídeo enfileirado!*\n📌 Tema: {tema}\n🎨 Estilo: {estilo}\n⏳ Aguarde...")
    pos = gerenciador.adicionar(
        f"Vídeo: {tema}",
        _tarefa_video,
        (tema, formato, estilo, para)
    )
    if pos > 1:
        enviar(para, f"📋 Posição na fila: {pos}º")


# ══════════════════════════════════════════════════════════
#  CORTES YOUTUBE
# ══════════════════════════════════════════════════════════
def _tarefa_cortes(url_yt, num_cortes, para):
    if cancelado():
        enviar(para, "⚠️ Tarefa cancelada antes de iniciar.")
        return

    arq_yt = f"{PASTA}/yt_original.mp4"
    ret = os.system(f'yt-dlp -f "best[height<=720]" -o "{arq_yt}" "{url_yt}" 2>/dev/null')

    if ret != 0 or not os.path.exists(arq_yt):
        enviar(para, "❌ Não consegui baixar. Verifique o link.")
        return

    dur = duracao(arq_yt)
    titulo = gemini(f"Sugira um tema em 3 palavras para um vídeo de {dur:.0f} segundos.")
    enviar(para, f"⬇️ Vídeo baixado! ({dur:.0f}s)\n✂️ Gerando {num_cortes} cortes...")

    analise = gemini(
        f"Vídeo de {dur:.0f} segundos. Sugira {num_cortes} cortes virais de 30-45s. "
        "Formato: INICIO-FIM em segundos. Ex: 45-90. Um por linha."
    )

    cortes = []
    for linha in analise.split("\n"):
        match = re.search(r'(\d+)\s*[-–]\s*(\d+)', linha)
        if match:
            ini, fim = int(match.group(1)), int(match.group(2))
            if fim > ini and fim <= dur and (fim - ini) <= 60:
                cortes.append((ini, fim))

    if not cortes:
        intervalo = int(dur / num_cortes)
        cortes = [(i*intervalo, min(i*intervalo+40, dur)) for i in range(num_cortes)]

    cortes_gerados = []
    for i, (ini, fim) in enumerate(cortes[:num_cortes]):
        if cancelado():
            enviar(para, f"⚠️ Cancelado! {len(cortes_gerados)} cortes já foram salvos.")
            return

        saida = f"{PASTA}/cortes/EMC3_IA_corte_{i+1:02d}.mp4"
        dur_c = fim - ini

        os.system(
            f"ffmpeg -y -ss {ini} -i {arq_yt} -t {dur_c} "
            f"-vf \"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,setsar=1,"
            f"drawtext=text='EMC\u00b3 IA':"
            f"fontcolor=white@0.8:fontsize=40:"
            f"x=(w-text_w)/2:y=60:"
            f"box=1:boxcolor=black@0.5:boxborderw=12\" "
            f"-c:v libx264 -preset ultrafast -crf 22 "
            f"-c:a aac -b:a 128k "
            f"{saida} 2>/dev/null"
        )

        if os.path.exists(saida):
            os.system(f"termux-media-scan {saida} 2>/dev/null")
            cortes_gerados.append(saida)
            texto = gerar_texto_viral(f"corte {i+1} - {titulo}")
            enviar_midia(para, saida,
                f"✂️ *Corte {i+1}/{num_cortes}* ✅\n\n📝 {texto[:600]}")
            time.sleep(2)

    enviar(para, f"🎉 *Concluído!* {len(cortes_gerados)} cortes na galeria!")


def gerar_cortes_youtube(url_yt, num_cortes, para):
    enviar(para, f"✂️ *Cortes enfileirados!*\n🔗 {url_yt[:50]}...\n📊 {num_cortes} cortes\n⏳ Aguarde...")
    pos = gerenciador.adicionar(
        f"Cortes YouTube ({num_cortes})",
        _tarefa_cortes,
        (url_yt, num_cortes, para)
    )
    if pos > 1:
        enviar(para, f"📋 Posição na fila: {pos}º")


# ══════════════════════════════════════════════════════════
#  WEBHOOK WHATSAPP
# ══════════════════════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
    de = request.form.get("From", "").replace("whatsapp:", "")
    corpo = request.form.get("Body", "").strip()
    tipo_midia = request.form.get("MediaContentType0", "")
    url_midia = request.form.get("MediaUrl0", "")
    num_midias = int(request.form.get("NumMedia", 0))

    print(f"\n📱 [{de}]: {corpo}")
    threading.Thread(
        target=processar_mensagem,
        args=(de, corpo, tipo_midia, url_midia, num_midias)
    ).start()
    return "", 200


def processar_mensagem(de, corpo, tipo_midia, url_midia, num_midias):
    c = corpo.lower().strip()

    # ── Áudio de voz ──
    if num_midias > 0 and "audio" in tipo_midia:
        enviar(de, "🎙️ Transcrevendo seu áudio...")
        texto = transcrever_audio(url_midia)
        if texto:
            enviar(de, f"🗣️ Entendi: *{texto}*\n⚙️ Processando...")
            processar_mensagem(de, texto, "", "", 0)
        else:
            enviar(de, "❌ Não entendi o áudio. Tente digitar!")
        return

    # ── Cancelar ──
    if any(p in c for p in ["cancelar", "cancela", "para", "stop"]):
        gerenciador.cancelar()
        enviar(de, "⛔ *Tarefa cancelada!*\nFila limpa. Pronto para novos comandos!")
        return

    # ── Status ──
    if any(p in c for p in ["status", "situação", "andamento", "fila"]):
        atual, na_fila = gerenciador.status()
        if atual:
            enviar(de,
                f"📊 *Status EMC³ IA*\n\n"
                f"⚙️ Executando: *{atual}*\n"
                f"📋 Na fila: *{na_fila}* tarefa(s)\n\n"
                f"_Digite 'cancelar' para parar tudo_"
            )
        else:
            enviar(de, "✅ *EMC³ IA livre!*\nNenhuma tarefa em andamento.\nPronto para seus comandos!")
        return

    # ── Link YouTube ──
    if "youtube.com" in c or "youtu.be" in c:
        match = re.search(r'https?://\S+', corpo)
        if match:
            n = 5
            match_n = re.search(r'(\d+)\s*cortes?', c)
            if match_n:
                n = min(int(match_n.group(1)), 10)
            gerar_cortes_youtube(match.group(), n, de)
        return

    # ── Ajuda / Menu ──
    if any(p in c for p in ["ajuda", "help", "menu", "oi", "olá", "ola", "emc", "início", "inicio"]):
        menu_txt = (
            "🤖 *EMC³ IA v3.0*\n\n"
            "🎬 *Vídeo viral:*\n"
            "_cria vídeo sobre meditação_\n"
            "_vídeo motivacional sobre sucesso_\n"
            "_vídeo educativo sobre saúde_\n\n"
            "✂ *Cortes YouTube:*\n"
            "_Cole o link do YouTube_\n"
            "_3 cortes [link]_\n\n"
            "📝 *Texto + Hashtags:*\n"
            "_text
