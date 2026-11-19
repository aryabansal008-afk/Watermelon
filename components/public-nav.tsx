import Link from "next/link";
import { Brand } from "./brand";
import { Button } from "./ui/button";
export function PublicNav() { return <header className="public-nav"><Brand /><span className="project-recall-tag">By Bina Logic</span><nav aria-label="Main navigation"><Link href="/features">Features</Link><Link href="/how-it-works">How it works</Link><Link href="/docs">Docs</Link><a href="https://github.com" target="_blank" rel="noreferrer">GitHub</a></nav><div className="nav-actions"><Link href="/login" className="signin-link">Sign in</Link><Button asChild size="sm"><Link href="/onboarding">Get started</Link></Button></div></header>; }
