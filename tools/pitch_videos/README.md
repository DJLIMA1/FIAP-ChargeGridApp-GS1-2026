# Vídeos de interação do pitch

Um script por fluxo em `flows/`, todos sobre o mesmo harness (`recorder.py` para o app e o painel,
`totem.py` para o totem), então todos os vídeos têm o mesmo toque, ritmo e codificação.

| Superfície | Origem | Saída |
|---|---|---|
| App (Flet, conta demo em memória) | `AppSession` · 402×874 pt @3x | `output/pitch-videos/app/*.mp4` · 1080×2348 (celular) |
| Painel web (owner-web, `npm run dev:mock` em `localhost:5179`) | `WebSession` · 1440×810 @4/3 | `output/pitch-videos/web/*.mp4` · 1920×1080 (16:9) |
| Totem (LVGL real, quadros de `tools/validate_firmware.py --output tmp/pitch-totem-frames`) | `totem.build` | `output/pitch-videos/totem/*.mp4` · 1600×960 (5:3) |

Todos: H.264 30 fps, yuv420p, CRF 16, faststart, sem áudio (prontos para o Canva).

```bash
.venv/bin/python tools/pitch_videos/flows/app_01_login.py
```

Regras de estilo (iguais para todos os fluxos):

- Tema escuro, conta demo, dados de demonstração; nada de splash/carregando no começo (o harness só grava depois da primeira tela).
- Tempos só pelas constantes `PACE` (abertura 1,2 s, 1 s após cada toque, 2 s para ler, 2 s no fim, digitação 14 car/s).
- Toque = anel branco com preenchimento translúcido (app e totem); no painel, cursor de seta com pulso no clique.
- Cada vídeo mostra um fluxo completo e termina na tela de resultado; 8–35 s.
- Preparações fora de câmera com `pause()`/`resume()`; nunca editar o app para gravar.
- Até `CG_PITCH_SLOTS` (padrão 4) gravações ao mesmo tempo; as demais esperam a vez.
