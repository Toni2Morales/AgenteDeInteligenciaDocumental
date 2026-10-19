# Demostración de DocuMind AI

Este directorio contiene los recursos para una demostración reproducible del sistema: un documento
de ejemplo y un conjunto de preguntas de evaluación.

## Contenido

| Archivo | Descripción |
| --- | --- |
| `document.txt` | Fuente de texto del documento de demostración (contenido original y propio, con datos públicos y estables sobre el Sistema Solar). |
| `document.pdf` | PDF de demostración generado a partir de `document.txt`. |
| `evaluation.json` | Conjunto de preguntas de evaluación con respuesta esperada, página y sección de origen. |

El documento tiene **4 páginas**, una por sección:

1. El Sol
2. Los planetas interiores
3. Los planetas exteriores
4. Otros cuerpos y datos generales

El contenido es original del proyecto y recoge datos públicos, por lo que puede redistribuirse sin
problemas de derechos de autor.

## Cómo regenerar el PDF

El PDF se genera de forma **determinista** a partir de la fuente de texto: la misma fuente produce
siempre los mismos bytes. Para regenerarlo:

```powershell
python scripts/generate_demo_pdf.py
```

Esto reescribe `demo/document.pdf` a partir de `demo/document.txt`. Los separadores de página en la
fuente son líneas con el marcador `[[PAGE]]`.

## Cómo usar el documento y las preguntas de evaluación

1. Arranca la aplicación (ver el `README.md` principal).
2. Sube el documento con el endpoint de ingesta:

   ```powershell
   curl.exe -X POST "http://127.0.0.1:8000/api/documents/upload" -F "file=@demo\document.pdf"
   ```

3. Para cada entrada de `demo/evaluation.json`, formula la pregunta `question` y comprueba que la
   respuesta obtenida coincide con `expected_answer` y cita la `source_page` indicada.

Cada entrada de `evaluation.json` tiene estos campos:

| Campo | Significado |
| --- | --- |
| `id` | Identificador único de la pregunta. |
| `question` | Pregunta que se plantea al sistema. |
| `expected_answer` | Respuesta correcta esperada. |
| `source_page` | Página del PDF donde está la evidencia (1-indexada). |
| `source_section` | Sección del documento que contiene la evidencia. |

## Limitaciones

- Todavía no hay RAG, embeddings ni modelo de lenguaje: este material sirve para **preparar y
  evaluar** esas fases más adelante. De momento las preguntas se validan contra el texto extraído,
  no contra respuestas generadas.
- El documento es corto y sus datos son públicos y estables, de modo que las respuestas esperadas no
  cambian con el tiempo.
