# StreakChess – Canal de YouTube automático (vídeos largos)

Dos vídeos por semana de 8-12 min sobre cálculo y táctica, generados, subidos y optimizados solos.

| Cuándo se genera | Cuándo se publica |
|---|---|
| Martes 19:00 UTC | En cuanto termina (~20:00 UTC, 16:00 Nueva York en verano) |
| Viernes 19:00 UTC | En cuanto termina |

Nada más publicarse, se sube una **Story a Instagram** (@streakchess): los primeros 15 s del vídeo con el título y "Watch the full video · Link in bio". La API de Instagram no permite poner un sticker de enlace clicable, así que la Story manda al **enlace de la bio**: pon ahí tu canal de YouTube (o una página tuya que enlace al último vídeo). Te llega además un aviso (issue de GitHub → email) con el enlace al vídeo.

¿Quieres volver a tener margen para vetar? En GitHub → Settings → Secrets and variables → Actions → **Variables**, crea `YT_VETO_HOURS` (por ejemplo `24`): el vídeo se subirá privado y programado, y en ese modo no se publica la Story.

## Formatos (el piloto automático los rota y aprende cuál funciona)
- **Calculation Gym**: un curso progresivo (horquilla → clavada → enfilada → … → jugadas candidatas). Demo explicada, 4 repeticiones de dificultad creciente con temporizador y pista, la "jugada tentadora" que falla y la Regla del Coach.
- **Streak Challenge**: 10 puzzles de 800 a 2400, barra de racha en pantalla, puzzle jefe final y rango según tu puntuación (Peón → Gran Maestro).
- **Legendary Games**: partida histórica que se para en los momentos críticos: ¿qué jugarías tú?
- **This Week in Chess**: lo más fresco. Descarga las partidas de élite de la semana (retransmisiones oficiales de Lichess), Stockfish encuentra el golpe táctico que un GM encontró… o falló, y se convierte en reto.

## El equipo: 10 agentes que aprenden con cada vídeo
| Agente | Se encarga de |
|---|---|
| Trend Scout | Noticias de ajedrez de la semana (búsqueda web) y lo que la gente busca en YouTube |
| Showrunner | Concepto del episodio, continuidad de la serie, nota final de calidad |
| Head Writer | El guion completo |
| Chess Coach | Que el ajedrez sea correcto y se aprenda de verdad; pistas sin spoiler |
| Voice & Humor Editor | Que suene a youtuber real y con gracia; elimina frases típicas de IA |
| Visual Director | Palabras clave en pantalla, casillas iluminadas, pausas |
| Caption Editor | Subtítulos y traducciones (es, pt, hi, fr, de) |
| SEO Specialist | Título, descripción, tags, hashtags y títulos traducidos |
| Thumbnail Designer | Parejas título + texto de miniatura |
| Channel Analyst | Lee resultados y comentarios y reescribe el cuaderno de cada agente |

Cada agente tiene su cuaderno en `youtube/agents/<nombre>.md`. Tras cada vídeo, el Analista lo reescribe con lo que los demás tuvieron que corregir y, cuando hay datos, con los resultados reales (CTR, % visto, suscriptores, comentarios). Puedes leer en GitHub qué ha aprendido cada uno.

## Garantías
- Las jugadas salen siempre del código (Lichess, partidas verificadas con python-chess, Stockfish). Cualquier frase que mencione una jugada no permitida en ese momento (inventada o spoiler antes del temporizador) se elimina.
- Notación algebraica en pantalla y subtítulos (Nxf7+, O-O, 17...Be6!!); la voz la lee en inglés natural ("knight takes f7, check").
- Subtítulos palabra a palabra sincronizados con la voz, más archivo SRT subido a YouTube con traducciones.
- Nada de etiquetas internas en pantalla ("Hook", "Chapter"...).

## Configuración (una sola vez, ~20 min)
1. **Google Cloud** (console.cloud.google.com), con la cuenta dueña del canal:
   - Crea un proyecto → habilita **YouTube Data API v3** y **YouTube Analytics API**.
   - *Pantalla de consentimiento OAuth*: tipo Externo, añade tu email como usuario de prueba y luego pulsa **Publicar aplicación (In production)**. Si se queda en "Testing", el token caduca cada 7 días.
   - *Credenciales → Crear ID de cliente OAuth → Aplicación de escritorio*. Copia el Client ID y el Client Secret.
2. En tu ordenador: `pip install requests` y `python youtube/yt_auth.py CLIENT_ID CLIENT_SECRET`. (Si ya lo hiciste antes de octubre 2026, repítelo una vez: ahora pide también permiso para subir subtítulos.) Acepta en el navegador (elige el canal StreakChess) y copia el `YT_REFRESH_TOKEN` que imprime.
3. GitHub → Settings → Secrets and variables → Actions → **Secrets**: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` (`GEMINI_API_KEY` ya existe).
   Opcional en **Variables**: `YT_VOICE` (voz Gemini; por defecto la misma de los reels), `YT_PUBLISH_HOUR_UTC` (por defecto 21).
4. **Auditoría de la API (importante)**: los proyectos de API nuevos sin verificar solo pueden subir vídeos privados. Pide la auditoría gratuita en el formulario "YouTube API Services – Audit and Quota Extension" indicando que subes vídeos a tu propio canal. Mientras tanto los vídeos quedan en privado: puedes publicarlos a mano.
5. El canal debe estar **verificado por teléfono** (youtube.com/verify) para poder poner miniaturas propias.

## Probar sin publicar
Actions → *YouTube long videos* → *Run workflow* → elige formato, deja marcado "Only generate the video". El vídeo, las 2 miniaturas, el guion (`plan.json`) y la descripción quedan en *Artifacts*.

## Pausar
Actions → *YouTube long videos* → "…" → *Disable workflow*.

## Archivos
- `yt_run.py` orquesta · `yt_agents.py` el equipo · `yt_script.py` guion y formatos · `yt_package.py` SEO, miniaturas, traducciones · `yt_render.py` vídeo · `yt_notation.py` notación · `yt_engine.py` Stockfish · `yt_trends.py` tendencias · `yt_api.py` YouTube · `yt_strategy.py` piloto automático · `yt_library.py` partidas legendarias · `yt_puzzles.py` puzzles por tema.
- Estado: `yt_log.jsonl`, `yt_performance.json`, `yt_arms.json`, `yt_report.md`, `yt_playbook.md`, `thumbs/`.
- Comparte `used.json` con los reels: un puzzle nunca sale dos veces en la marca.
