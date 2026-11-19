import { redirect } from "next/navigation";
export default async function Page({params}:{params:Promise<{projectId:string}>}){redirect(`/workspace/${(await params).projectId}/dashboard`);}
