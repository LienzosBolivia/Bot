# V2 experimental

Dos hipótesis añadidas en desarrollo: `V2_regime_score` mezcla DSR × ROI solo con retorno histórico condicional positivo en el régimen; `V2_alpha_carry` aplica esa mezcla sin carry y usa la señal carry original como alternativa cuando no hay alfa elegible. CASH sigue disponible. No se ajustaron ventanas ni umbrales tras observar resultados.

`v2_comparison.csv` compara ambas con C original en el mismo período y con costes extra de 0, 2 y 5 bps por giro. `v2_hourly.csv` guarda retornos horarios, precio, funding, costes y activaciones del freno. `v2_allocations.csv` registra asignaciones por ciclo. `v2_validation.csv` registra elegibilidad. `v2_planned_price_attribution.csv` es atribución de precio planificada, NO beneficio neto realizado por estrategia; no incorpora el freno. La reconciliación de componentes se realiza a nivel cartera.

El drawdown horario mide cierres horarios, no mínimos intravela. El freno se reinicia por ciclo y puede exceder 4% por saltos y costes. No se certifica ausencia de leakage por la coincidencia entre simuladores. Se mantiene el modelo de pesos original, sin deriva de pesos ni modelado completo de margen, liquidación o llenado de órdenes. La sensibilidad de costes conserva las señales/selecciones del escenario base y recalcula el freno; no reentrena el validador con costes mayores.

Los nuevos experimentos se suman al historial de búsqueda; el DSR de 18 candidatas no corrige todas las decisiones de investigación previas. El holdout no se evalúa. Ninguna variante se promueve automáticamente por ganar en desarrollo.
