# ADR-002: Few-Shot Injection per il Self-Improving Loop vs Fine-Tuning

**Data:** 2026-04-28  
**Stato:** Accettato

## Contesto
L'agente deve migliorare nel tempo in base agli override degli operatori.
Le alternative principali erano: (1) few-shot injection nel system prompt, (2) fine-tuning del modello, (3) RAG con embedding.

## Decisione
Few-shot injection nel system prompt, aggiornata ogni 10 override significativi (categoria cambiata).

## Ragionamento
- **Ciclo di feedback immediato**: i few-shot si aggiornano in secondi. Il fine-tuning richiede cicli di giorni e infrastruttura ML dedicata — non realistica per un hackathon e costosa in produzione.
- **Trasparenza totale**: l'operatore può vedere esattamente quali esempi sta usando l'agente — nessuna black box. In un contesto regolamentato come le utility questo è un requisito implicito.
- **Reversibilità**: se un operatore inserisce un feedback sbagliato, basta cancellarlo dal feedback store. Con il fine-tuning, "disimparare" richiede un nuovo training run.
- **Fallback graceful**: se il feedback store è vuoto (prima deployment), l'agente funziona normalmente con il prompt base — zero dependency su dati storici all'avvio.

## Meccanismo concreto
1. Operatore fa override → `FeedbackEntry` salvato in SQLite
2. Ogni 10 override con categoria cambiata → `refresh_few_shots()` rigenera `FewShotExample`
3. Al prossimo `triage_email()` → `get_few_shot_prompt()` inietta gli esempi nel system prompt
4. `AccuracySnapshot` traccia il trend di accuratezza nel tempo

## Cosa abbiamo deliberatamente scelto di NON fare
- **Fine-tuning**: troppo costoso e lento per il ciclo hackathon; da valutare in produzione dopo 6+ mesi di feedback
- **Embedding similarity (RAG)**: utile sopra i ~1000 feedback, non giustifica la dipendenza da un vector store ora
- **Aggiornamento real-time per ogni override**: il batch da 10 evita che un singolo override rumoroso distorca il comportamento

## Conseguenze
- Il sistema migliora in modo discontinuo (ogni 10 override), non continuo — da comunicare agli operatori
- Dopo ~100 override significativi si dovrebbe valutare il passaggio a RAG per trovare esempi semanticamente simili, non solo per categoria
- La finestra di few-shot è limitata a 5 esempi — evitare prompt bloat

## Hook vs Prompt per i guardrail
- **Hook `PreToolUse`**: blocco deterministico su `route_ticket` se confidence < 0.5 o categoria emergenza. È un hook perché deve essere garantito indipendentemente da come evolve il sistema prompt.
- **Prompt**: preferenze sull'escalation dei clienti vulnerabili. È un prompt perché è una preferenza probabilistica, non un requisito binario, e può essere sfumata da contesto.
