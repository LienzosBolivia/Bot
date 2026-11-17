# V3 — pruebas de propuestas, no promoción automática

Hipótesis fijadas antes de esta ejecución:

- Control C con universo estadístico común de 22 candidatas.
- Sustituir carry original por carry con entrada media 168h > 0.00005 y salida < -0.00015.
- Añadir rupturas de cierres de 120/240/360h, solo largas, entrada con eficiencia 72h > 0.25; salida al romper canal inferior de 60/120/180h. El filtro es de eficiencia direccional, no volatilidad. Solo restringe la entrada; no fuerza un 25% de actividad.

Las tres variantes utilizan el DSR aproximado sobre las mismas 22 series, lo que modifica el benchmark respecto a V2. No se mezclan ambas mejoras en otra variante ni se busca un umbral óptimo. Esto no corrige todo el historial de investigación del proyecto. La sensibilidad +5bps mantiene decisiones base y vuelve a simular costes/freno. Se exportan exposición y giro por separado. Los meses parciales están incluidos en el recuento de meses positivos.

No se prueba como sistema ejecutable la propuesta 80% spot / 20% margen: pesos +0.8/-0.8 representan nominal bruto de 160% del patrimonio y requieren un modelo de garantías y liquidación. +0.6/-0.4 representa nominal bruto de 100%, no automáticamente apalancamiento 100%. La neutralidad direccional no elimina riesgo de margen. Escalar un nominal de 0.5 a 0.8 multiplica por 1.6 las contribuciones lineales bajo supuestos constantes, no convierte automáticamente 1.96% en 4.5%.

La contabilidad heredada no modela llenado a próxima apertura, deriva de pesos, margen ni liquidación. Los resultados son pruebas de hipótesis bajo ese modelo, no certificación para operar en vivo. Los componentes precio/funding/costes son sumas de retornos horarios, no atribución compuesta del ROI. Eliminar los tres mejores ciclos es una medida de concentración, no una prueba estadística de ausencia de ventaja, y no se usa como objetivo a optimizar repetidamente.

El holdout continúa sin evaluar. Pruebas sintéticas ejecutadas: causalidad por prefijos, número de candidatas, ausencia de cortos en las nuevas rupturas y ejecución integrada.
