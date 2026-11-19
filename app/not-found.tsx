import Link from "next/link";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
export default function NotFound(){return <main id="main" className="page-public"><Brand/><div className="empty"><h2>This slice is missing.</h2><p>The page or record could not be found.</p><Button asChild><Link href="/">Back home</Link></Button></div></main>;}
