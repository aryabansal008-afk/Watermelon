"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { api } from "@/lib/api";
import { Empty, Status } from "./workspace";
import { Button } from "./ui/button";

type Run = { id: string; model: string; status: string; metrics: Record<string, number>; input_hash: string; output_hash: string };

export function Benchmark({ runId }: { runId?: string }) {
  const [data, setData] = useState<{ runs: Run[] } | Run | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ runs: Run[] } | Run>(`/benchmark${runId ? `/runs/${runId}` : ""}`)
      .then(setData).catch((e) => setError(e.message));
  }, [runId]);

  return <>
    <span className="eyebrow">BLIND PYTHON PEP BENCHMARK</span>
    <h1>Evidence, put to the test.</h1>
    <p className="lede">Can engineering discussions reveal rejected alternatives without access to the answer key? Reproducible inputs. Isolated ground truth. No invented scores.</p>
    <div className="panel">
      {error ? <Empty title="Benchmark records require a workspace session." text={error} action={<Button asChild><Link href="/login">Sign in</Link></Button>} />
        : !data ? <div className="empty" role="status">Loading benchmark records…</div>
        : "runs" in data ? data.runs.length
          ? <div className="decision-list">{data.runs.map((run) => <Link className="decision-card" key={run.id} href={`/benchmark/${run.id}`}><h2>{run.model}</h2><Status value={run.status} /></Link>)}</div>
          : <Empty title="No benchmark scores yet." text="Four public discussion snapshots are frozen: PEP 703 and 723 for development, and PEP 750 and 824 held out by PEP. No model predictions or independent human adjudications are recorded, so no metrics are available." />
        : <div className="detail-main"><h2>{data.model}</h2><Status value={data.status} />{Object.entries(data.metrics).map(([key, value]) => <div className="metadata-item" key={key}><label>{key}</label><p>{value}</p></div>)}<p className="evidence-hash">Input {data.input_hash}<br />Output {data.output_hash}</p></div>}
    </div>
    <div className="feature-grid" style={{ marginTop: 30 }}>
      {[["Blind extraction", "Only selected public conversation snapshots enter the extractor."], ["Isolated evaluation", "PEP answer keys enter the evaluator after predictions are frozen."], ["Reproducible scoring", "One-to-one matches, rationale judgments, and citation support are recorded alongside hashes."]].map(([title, body]) => <div className="panel feature-panel" key={title}><FlaskConical size={25} /><h2>{title}</h2><p>{body}</p></div>)}
    </div>
  </>;
}
