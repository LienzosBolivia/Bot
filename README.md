# Bot — laboratorio BTC/BNB

Código de referencia del ensayo proporcionado por el usuario. No envía órdenes a un exchange.

## Ejecutar en Google Colab

Abrir [Colab](https://colab.research.google.com/github/LienzosBolivia/Bot/blob/main/Colab.ipynb) y ejecutar su única celda. Cada ejecución actualiza la copia de `main`, instala `requirements.txt` y arranca un proceso Python nuevo. No necesita token mientras el repositorio sea público.

También se puede pegar esta celda en un notebook propio:

```python
import requests
url = 'https://raw.githubusercontent.com/LienzosBolivia/Bot/main/colab_bootstrap.py'
response = requests.get(url, timeout=30, headers={'Cache-Control': 'no-cache'})
response.raise_for_status()
exec(compile(response.text, url, 'exec'))
```

El código ejecutado se mantiene en GitHub. Después de una corrección basta con volver a ejecutar la misma celda, sin reiniciar el entorno de Colab. La copia `/content/bot` es desechable: no editarla manualmente, pues se restablece a `origin/main`. Los resultados se conservan aparte en `/content/bot_results` mientras dure la máquina de Colab. Descargar el ZIP para conservarlos después de cerrar la sesión.

El ZIP se descarga al finalizar o al producirse un error de ejecución. Incluye `execution.log`, `colab.log`, `status.json` (commit, versiones, estado y error), CSV y `equity_dev.png` cuando se hayan generado. Compartir el ZIP o el log y su commit para diagnosticar. Si falla antes de iniciar el script (por ejemplo, Git o instalación), compartir la salida de la celda.

## Archivos

- `research.py`: datos, 18 candidatas, DSR, walk-forward y diagnósticos.
- `run.py`: ejecución, registro de errores y exportación de resultados.
- `colab_bootstrap.py`: actualización del repositorio y ejecución en Colab.
- `requirements.txt`: versiones directas fijadas para reproducibilidad.
- `test_research.py`: pruebas sintéticas sin conexión ni holdout.

## Ejecutar localmente

Recomendado Python 3.11 o 3.12, en un entorno virtual.

```bash
python -m pip install -r requirements.txt
python -m unittest -v
python -u run.py
```

## Alcance de esta integración

Se normalizaron los escapes HTML/Markdown del mensaje original y se separó el arranque de los cálculos. Se mantienen el rango UTC 2024-10-31 00:00 a 2026-09-30 15:00, las 16.792 velas, la partición 12.594/4.198, las reglas de selección, comisiones, funding y kill-switch originales. El gráfico se exporta y se muestra en Colab. El holdout se carga y comprueba como en el original, pero no se evalúa ni se utiliza para seleccionar estrategias.

La prueba de coincidencia de simuladores comprueba consistencia interna, no demuestra realismo financiero. Esta integración no certifica el DSR ni corrige hipótesis de ejecución, financiación, rebalanceo, margen, deslizamiento o drawdown medido solo cada 72h. El calendario de funding de 8h se conserva como validación estricta: si los datos contradicen esa hipótesis, el programa se detiene para revisión, sin rellenar eventos.

No se configura GitHub Actions ni publicación automática de logs: el flujo acordado es ejecutar manualmente en Colab y compartir los resultados.
