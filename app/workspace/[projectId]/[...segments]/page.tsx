import { Suspense } from "react";
import { notFound } from "next/navigation";
import { WorkspacePage } from "@/components/workspace";
const routes = ["dashboard","projects","decisions","discussions","knowledge-graph","timeline","code","pull-requests","ask","integrations","settings"];
export default async function Page({params}:{params:Promise<{projectId:string;segments:string[]}>}){const {projectId,segments}=await params;if(!routes.includes(segments[0])||segments.length>2||(segments.length===2&&!["decisions","discussions","pull-requests"].includes(segments[0])))notFound();return <Suspense fallback={<p role="status">Loading memory…</p>}><WorkspacePage projectId={projectId} segments={segments}/></Suspense>;}
