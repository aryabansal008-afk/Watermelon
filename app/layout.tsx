import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: { default: "WATERMELON - Old Decisions, Smarter Code.", template: "%s · WATERMELON" }, description: "Evidence-grounded engineering memory. Find the decisions, debates, and context behind your code." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><a className="skip-link" href="#main">Skip to content</a>{children}</body></html>;
}
