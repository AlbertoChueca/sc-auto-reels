# StreakChess – Reels automáticos

Cada día publica 3 reels en @streakchess:

| Hora (Nueva York) | Nivel | Rango |
|---|---|---|
| 12:00 | Beginner | 800–1200 |
| 18:00 | Intermediate | 1200–1900 |
| 21:00 | Advanced | 1900–2500 |

(En invierno salen una hora antes, porque GitHub usa horario UTC.)

Qué hace cada ejecución: elige un puzzle nuevo de la base de datos de Lichess (nunca repite: los usados quedan en `used.json`), genera el vídeo, lo sube a Instagram con descripción y hashtags, y anota el enlace en `log.jsonl`.

## Secrets necesarios (Settings → Secrets and variables → Actions)
- `IG_TOKEN`: el token de Instagram (obligatorio).
- `GH_PAT`: opcional. Solo para que la renovación automática del token pueda guardarlo si Instagram lo cambia.

## Probar sin publicar
Actions → *Daily reels* → *Run workflow* → deja marcado "Only generate the video". Al terminar, el vídeo se descarga desde la sección *Artifacts* de esa ejecución.

## Pausar
Actions → *Daily reels* → botón "…" → *Disable workflow*.
