# ADR-001: Coordinator + Specialist Tools vs Agente Monolitico

**Data:** 2026-04-28  
**Stato:** Accettato

## Contesto
Dobbiamo classificare email di reclamo e instradarle a 8 uffici diversi.
L'alternativa principale era un singolo agente con un prompt molto lungo vs un coordinator che orchestra tool specializzati.

## Decisione
Coordinator con 4 tool specializzati: `classify_complaint`, `get_customer_history`, `get_similar_cases`, `route_ticket`.

## Ragionamento
- **Affidabilità per numero di tool**: la letteratura e i benchmark interni mostrano che la reliability del tool-selection cala significativamente oltre 5-6 tool. Mantenendo 4 tool il coordinator mantiene alta precisione nella scelta.
- **Separazione delle responsabilità**: classify non fa routing, route non fa classificazione. Ogni errore è isolato e loggabile.
- **Stop reason handling esplicito**: il loop gestisce `tool_use` vs `end_turn` in modo deterministico, non basato su parsing del testo.
- **Audit trail**: ogni tool call è loggata separatamente — in produzione ogni decisione è replayable dal log.

## Cosa abbiamo deliberatamente scelto di NON fare
- **Subagent separati per specialist**: il vantaggio in latenza non giustifica la complessità aggiuntiva di context passing esplicito per questo caso d'uso. Il pattern subagent è adatto quando ogni specialist ha un tool set completamente diverso.
- **Chain of Thought forzato**: il coordinator produce il reasoning nel JSON finale, non in un CoT separato — meno token, più strutturato.
- **RAG vettoriale**: il feedback store usa query SQL sul DB, non embedding similarity. Per la dimensione attuale (<1000 feedback) è più veloce e trasparente.

## Conseguenze
- Ogni aggiunta di tool richiede valutazione dell'impatto su reliability (max 5 tool)
- Il coordinator system prompt deve essere aggiornato quando cambiano le categorie
