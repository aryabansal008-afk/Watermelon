"use client";
import { Button } from "@/components/ui/button";
export default function ErrorPage({reset}:{error:Error;reset:()=>void}){return <main id="main" className="page-public"><div className="panel empty"><h2>Something interrupted this view.</h2><p>Your source evidence is stored independently. Please retry the page.</p><Button onClick={reset}>Try again</Button></div></main>;}
