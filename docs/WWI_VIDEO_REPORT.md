# WWI — "E se a Primeira Guerra Mundial nunca terminasse?" (entrega live, 2026-11-04)

Vídeo de 30 s, vertical 9:16, estilo cinematográfico épico, em PT. Pedido do utilizador com
entrevista criativa (estilo épico / 30 s / vertical 9:16 por omissão do produto) e execução
autónoma com correcção e re-teste até produto final.

## Ficheiros (pasta Vídeos)

- `ClipForge_WWI_E_Se_A_Guerra_Nunca_Terminasse_30s_9x16.mp4` (4 300 958 bytes)
- `ClipForge_WWI_E_Se_A_Guerra_Nunca_Terminasse_contact.png` (contact sheet)
- `ClipForge_WWI_teste_cena{1,2,3,4}.png` (frames de teste por cena)

## Verificação técnica (ffprobe + QA do worker)

720×1280, h264/yuv420p, 24 fps, 720/720 frames, 30.00 s, sem áudio (sem narração —
o utilizador grava; sem TTS por regra). QA do render: 720 capturados, 0 em falta,
0 pretos, 0 congelados. 4 cenas (7.32/7.68/7.42/7.58 s), transições
dissolve/wipe/dissolve/fade, tipografia cinética, máscara, tracking, pop elástico,
contador de anos, barras, choque, partículas, divisor SVG, parallax multicamada
fundo+frente. Títulos medidos no DOM (top 10% exacto, sem corte); inspecção visual
das 4 cenas no motor real.

## Custos (tudo pago, nada mock)

| Passo | Custo real |
|---|---:|
| Storyboard live (Muse Spark, high effort) | $0.002782 |
| 6 plates Muse Image 1280×1920 | $0.060000 |
| Re-tentativa placa filtrada (1/2 reword, só 1 cobrada) | incluído acima |
| **Total** | **$0.062782** |

Tecto da ideia $0.10 respeitado; ledger de serviço inalterado (`22/24/8/16`);
total da missão $0.0628 de $5.00. Uma chamada de imagem falhada por filtro de
conteúdo não foi cobrada.

## Incidentes resolvidos (descobrir → corrigir → testar)

1. **Placa `asset_soldiers_fg` recusada (HTTP 400, filtro de conteúdo).** Prompt com
   soldados/arame farpado. Correcção: reescrita policy-safe da mesma composição
   (trincheira vazia) + preventiva em `asset_tank_fg` (sem pessoas), hashes de
   aprovação actualizados sob autorização explícita do utilizador, 1 re-tentativa
   manual (não automática). 6/6 geradas.
2. **Render `render_surface_timeout` (2×).** Causa-raiz: CORS — a superfície de
   captura corria em `:3002` mas o build data o API em `localhost:8000`, origem
   fora da allowlist. Correcção: stack nos portos do produto (`:3000` + `:8000`),
   requeue sem custo. Render verificado à primeira depois disso.

## Idea ID

`idea_99e2b9c04d6e` (storage isolado `storage/_wwi`, intacto para auditoria).
