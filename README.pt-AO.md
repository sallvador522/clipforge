# ClipForge (PT-AO)

**Estúdio de edição de vídeo com voz — descreve a edição, recebe um MP4 real.**

Criado por **António Salvador (Angola)**, com assistência substancial de desenvolvimento da **Muse Wonder da Meta**. A visão e a propriedade são do António; a Muse Wonder ajudou a construir, não corre dentro do produto.

## O que é
Dizes o que queres mudar num vídeo e um Director criativo (Muse Spark) planeia, pede aprovação e coordena modelos especializados + um motor real de produção (Anime.js, FFmpeg/OpenCV). O resultado é um MP4 verificado, não uma maqueta.

## Modelos Meta
- **Muse Spark 1.3** — percebe o pedido, planeia operações, chama ferramentas validadas.
- **Muse Voice Transcribe 1.0** — voz → texto (incl. legendas com tempos reais).
- **SAM 3.1** — segmenta pessoas; as máscaras reais isolam o sujeito.
- **Muse Image 1.0** — gera um fundo por trabalho aprovado.

Tudo o que é mock está etiquetado; nada renderiza sem aprovação; a chave API nunca chega ao browser.

## Correr localmente
```powershell
git clone https://github.com/sallvador522/clipforge.git
cd clipforge
powershell -ExecutionPolicy Bypass -File .\scripts\setup_judge.ps1
# cola a tua MODEL_API_KEY no .env, depois:
powershell -ExecutionPolicy Bypass -File .\scripts\start_judge.ps1
# abre http://localhost:3000
```
Sem chave: corre em mock (`scripts/dev_api.py` + `scripts/dev_worker.py` + `npm run dev` em `apps/web`) — mesma aplicação, $0,00.

Guia completo: [`docs/JUDGE_QUICKSTART.md`](docs/JUDGE_QUICKSTART.md) · Demonstração: [`docs/HACKATHON_DEMO_GUIDE.md`](docs/HACKATHON_DEMO_GUIDE.md) · Estado honesto das capacidades: `README.md` (tabela Capability status).

## Licença
MIT — ver [LICENSE](LICENSE).
