import { PublicNav } from "@/components/public-nav";
import { Benchmark } from "@/components/benchmark";
export default async function Page({params}:{params:Promise<{runId:string}>}){return <><div className="public-top"><PublicNav/></div><main id="main" className="page-public"><Benchmark runId={(await params).runId}/></main></>;}
