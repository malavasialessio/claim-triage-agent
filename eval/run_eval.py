"""
Eval harness per il CoordinatorAgent.
Gira sul golden set (ground truth nota) e sull'adversarial set.
Metriche: accuracy, precision per categoria, false-confidence rate, adversarial pass rate.

Uso: python eval/run_eval.py [--limit N] [--adversarial]
"""

import json
import sys
import argparse
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.coordinator import triage_email


def load_dataset(adversarial: bool = False) -> list[dict]:
    base = Path(__file__).parent.parent / "data"
    path = base / ("emails_adversarial.json" if adversarial else "emails_golden.json")
    return json.loads(path.read_text(encoding="utf-8"))


def run_eval(emails: list[dict], label: str) -> dict:
    results = []
    category_stats = defaultdict(lambda: {"total": 0, "correct": 0, "false_confident": 0})

    print(f"\n{'='*60}")
    print(f"  {label} — {len(emails)} email")
    print(f"{'='*60}")

    for i, email in enumerate(emails, 1):
        true_cat = email.get("true_category", "")
        true_pri = email.get("true_priority", "")
        email_id = email.get("id", f"eval_{i:04d}")

        print(f"  [{i:>3}/{len(emails)}] {email_id} (true: {true_cat})...", end=" ", flush=True)

        start = time.time()
        try:
            result = triage_email(email_id, email.get("subject", ""), email.get("body", ""))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                "email_id": email_id, "error": str(e),
                "true_category": true_cat, "pred_category": None,
                "correct": False, "confidence": 0.0,
            })
            continue
        elapsed = time.time() - start

        pred_cat = result.get("final_category", "")
        pred_pri = result.get("final_priority", "")
        confidence = result.get("confidence", 0.0)
        correct_cat = pred_cat == true_cat
        correct_pri = pred_pri == true_pri

        # False confidence: confidence alta (>=0.7) ma categoria sbagliata
        false_confident = (confidence >= 0.7) and not correct_cat

        category_stats[true_cat]["total"] += 1
        if correct_cat:
            category_stats[true_cat]["correct"] += 1
        if false_confident:
            category_stats[true_cat]["false_confident"] += 1

        status = "OK" if correct_cat else f"WRONG (pred={pred_cat})"
        fc_flag = " [FALSE-CONF]" if false_confident else ""
        print(f"{status}{fc_flag} conf={confidence:.2f} [{elapsed:.1f}s]")

        results.append({
            "email_id": email_id,
            "true_category": true_cat,
            "true_priority": true_pri,
            "pred_category": pred_cat,
            "pred_priority": pred_pri,
            "confidence": confidence,
            "correct_category": correct_cat,
            "correct_priority": correct_pri,
            "false_confident": false_confident,
            "needs_human_review": result.get("needs_human_review", False),
            "retry_count": result.get("retry_count", 0),
            "elapsed_s": round(elapsed, 2),
        })

    return {
        "label": label,
        "total": len(results),
        "results": results,
        "category_stats": dict(category_stats),
    }


def compute_metrics(eval_result: dict) -> dict:
    results = eval_result["results"]
    total = len(results)
    if total == 0:
        return {}

    correct = sum(1 for r in results if r.get("correct_category"))
    false_confident = sum(1 for r in results if r.get("false_confident"))
    human_review = sum(1 for r in results if r.get("needs_human_review"))
    errors = sum(1 for r in results if "error" in r)
    retried = sum(1 for r in results if r.get("retry_count", 0) > 0)

    per_category = {}
    for cat, stats in eval_result["category_stats"].items():
        t = stats["total"]
        c = stats["correct"]
        fc = stats["false_confident"]
        per_category[cat] = {
            "total": t,
            "precision": round(c / t, 3) if t > 0 else None,
            "false_confidence_rate": round(fc / t, 3) if t > 0 else 0.0,
        }

    return {
        "accuracy": round(correct / total, 4),
        "false_confidence_rate": round(false_confident / total, 4),
        "human_review_rate": round(human_review / total, 4),
        "error_rate": round(errors / total, 4),
        "retry_rate": round(retried / total, 4),
        "per_category": per_category,
    }


def print_report(label: str, metrics: dict):
    print(f"\n{'='*60}")
    print(f"  REPORT: {label}")
    print(f"{'='*60}")
    print(f"  Accuracy:              {metrics['accuracy']*100:.1f}%")
    print(f"  False confidence rate: {metrics['false_confidence_rate']*100:.1f}%  (confident & wrong)")
    print(f"  Human review rate:     {metrics['human_review_rate']*100:.1f}%")
    print(f"  Error rate:            {metrics['error_rate']*100:.1f}%")
    print(f"  Retry rate:            {metrics['retry_rate']*100:.1f}%")
    print(f"\n  Per-category precision:")
    for cat, s in sorted(metrics["per_category"].items(), key=lambda x: -(x[1]["precision"] or 0)):
        prec = f"{s['precision']*100:.0f}%" if s["precision"] is not None else "  —"
        fc = f"{s['false_confidence_rate']*100:.0f}%"
        print(f"    {cat:<30} {prec:>5}  (false-conf: {fc}, n={s['total']})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20, help="Max email da valutare (default 20)")
    parser.add_argument("--adversarial", action="store_true", help="Esegui solo adversarial set")
    parser.add_argument("--output", type=str, default=None, help="Salva risultati JSON su file")
    args = parser.parse_args()

    all_metrics = {}

    if not args.adversarial:
        golden = load_dataset(adversarial=False)[: args.limit]
        eval_result = run_eval(golden, "Golden Set")
        metrics = compute_metrics(eval_result)
        print_report("Golden Set", metrics)
        all_metrics["golden"] = metrics

    adv = load_dataset(adversarial=True)
    eval_result_adv = run_eval(adv, "Adversarial Set")
    metrics_adv = compute_metrics(eval_result_adv)
    print_report("Adversarial Set", metrics_adv)
    all_metrics["adversarial"] = metrics_adv

    print(f"\n{'='*60}")
    print("  SCORECARD FINALE")
    print(f"{'='*60}")
    if "golden" in all_metrics:
        g = all_metrics["golden"]
        print(f"  Golden accuracy:          {g['accuracy']*100:.1f}%")
        print(f"  Golden false-conf rate:   {g['false_confidence_rate']*100:.1f}%")
    a = all_metrics["adversarial"]
    print(f"  Adversarial pass rate:    {(1-a['accuracy'])*100:.1f}% attacchi rilevati")
    print(f"  Adversarial false-conf:   {a['false_confidence_rate']*100:.1f}%")

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(all_metrics, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Risultati salvati in: {out_path}")


if __name__ == "__main__":
    main()
