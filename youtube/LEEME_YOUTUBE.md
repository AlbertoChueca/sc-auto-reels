# StreakChess – Canal de YouTube automático (vídeos largos)

Dos vídeos por semana de 8-12 min sobre cálculo y táctica, generados, subidos y optimizados solos.

| Cuándo se genera | Cuándo se publica | Margen de veto |
|---|---|---|
| Lunes 05:00 UTC | Martes 21:00 UTC (17:00 Nueva York en verano) | ~40 h |
| Jueves 05:00 UTC | Viernes 21:00 UTC | ~40 h |

El vídeo se sube como **privado y programado**. Te llega un aviso (issue de GitHub → email) con el enlace a YouTube Studio. Si no haces nada, se publica solo. **Para vetarlo**: en Studio cambia la visibilidad a Privado sin programar, o bórralo.

## Formatos (el piloto automático los rota y aprende cuál funciona)
- **Lección explicada**: una idea táctica (horquilla, clavada, desviación, mates en 3, jugadas candidatas...) con 4 ejemplos de dificultad creciente, temporizador para pausar y calcular, solución animada y explicación.
- **Reto de puzzles**: 10 puzzles de ~800 a ~2400, temporizador, "apunta tu puntuación".
- **Partidas legendarias**: partida real (Morphy, Anderssen, Fischer, Kaspárov...) que se detiene en los momentos críticos para que calcules.

El ajedrez lo pone siempre el código (posiciones de Lichess, soluciones, material ganado, jugadas reales validadas con python-chess). Gemini solo escribe el guion alrededor y tiene prohibido inventar jugadas.

## Piloto automático
- Cada vídeo es un experimento: formato, tipo de gancho, estilo de título, estilo de miniatura, tiempo para pensar y tema.
- A los 5 días mide en YouTube Analytics: vistas, % visto, suscriptores, likes/comentarios y CTR de miniatura → aprende con Thompson sampling (`yt_report.md`).
- Los lunes un estratega reescribe `yt_playbook.md`, que usan los guionistas.
- **Rescate de miniatura**: si entre los días 3 y 10 el CTR está claramente por debajo de lo normal del canal, cambia sola a la miniatura B y al título alternativo.

## Configuración (una sola vez, ~20 min)
1. **Google Cloud** (console.cloud.google.com), con la cuenta dueña del canal:
   - Crea un proyecto → habilita **YouTube Data API v3** y **YouTube Analytics API**.
   - *Pantalla de consentimiento OAuth*: tipo Externo, añade tu email como usuario de prueba y luego pulsa **Publicar aplicación (In production)**. Si se queda en "Testing", el token caduca cada 7 días.
   - *Credenciales → Crear ID de cliente OAuth → Aplicación de escritorio*. Copia el Client ID y el Client Secret.
2. En tu ordenador: `pip install requests` y `python youtube/yt_auth.py CLIENT_ID CLIENT_SECRET`. Acepta en el navegador (elige el canal StreakChess) y copia el `YT_REFRESH_TOKEN` que imprime.
3. GitHub → Settings → Secrets and variables → Actions → **Secrets**: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` (`GEMINI_API_KEY` ya existe).
   Opcional en **Variables**: `YT_VOICE` (voz Gemini; por defecto la misma de los reels), `YT_PUBLISH_HOUR_UTC` (por defecto 21).
4. **Auditoría de la API (importante)**: los proyectos de API nuevos sin verificar solo pueden subir vídeos privados. Pide la auditoría gratuita en el formulario "YouTube API Services – Audit and Quota Extension" indicando que subes vídeos a tu propio canal. Mientras tanto los vídeos quedan en privado: puedes publicarlos a mano.
5. El canal debe estar **verificado por teléfono** (youtube.com/verify) para poder poner miniaturas propias.

## Probar sin publicar
Actions → *YouTube long videos* → *Run workflow* → elige formato, deja marcado "Only generate the video". El vídeo, las 2 miniaturas, el guion (`plan.json`) y la descripción quedan en *Artifacts*.

## Pausar
Actions → *YouTube long videos* → "…" → *Disable workflow*.

## Archivos
- `yt_run.py` orquesta · `yt_script.py` guion · `yt_render.py` vídeo + miniaturas · `yt_api.py` YouTube · `yt_strategy.py` piloto automático · `yt_library.py` partidas legendarias (añade más al final de `GAMES`; se validan solas) · `yt_puzzles.py` puzzles por tema.
- Estado: `yt_log.jsonl`, `yt_performance.json`, `yt_arms.json`, `yt_report.md`, `yt_playbook.md`, `thumbs/`.
- Comparte `used.json` con los reels: un puzzle nunca sale dos veces en la marca.
